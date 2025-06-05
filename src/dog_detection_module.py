#!/usr/bin/env python3
"""
Dog Detection and Search Module for Moorebot Scout
Uses computer vision to detect dogs, identify rooms, and coordinate with navigation
"""

import rospy
import cv2
import numpy as np
import requests
import json
import os
from datetime import datetime
from threading import Thread, Lock
import tf2_ros
import tf2_geometry_msgs

# ROS messages
from sensor_msgs.msg import Image, CompressedImage
from geometry_msgs.msg import PoseStamped
from std_msgs.msg import String, Bool
from cv_bridge import CvBridge

# Deep learning for object detection
try:
    import torch
    import torchvision.transforms as transforms
    from torchvision.models import detection
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    rospy.logwarn("PyTorch not available, using OpenCV cascade classifier for dog detection")

class DogDetectionModule:
    """
    Handles dog detection, room identification, and photo management
    """
    
    def __init__(self, navigation_controller):
        """Initialize dog detection module"""
        self.nav_controller = navigation_controller
        self.bridge = CvBridge()
        
        # Detection state
        self.dog_detected = False
        self.current_room = "unknown"
        self.detection_confidence = 0.0
        self.last_detection_time = None
        self.dog_location = None
        self.detection_active = False
        self.detection_lock = Lock()
        
        # Photo storage
        self.photo_dir = os.path.expanduser("~/scout_photos")
        os.makedirs(self.photo_dir, exist_ok=True)
        
        # Upload configuration
        self.upload_config = {
            'enabled': True,
            'service': 'local',  # Can be 'local', 'imgur', 'cloudinary', etc.
            'api_key': '',  # Set this for cloud services
            'webhook_url': ''  # Optional webhook for notifications
        }
        
        # Load room map for location identification
        self.load_room_map()
        
        # Initialize detection model
        self.setup_detection_model()
        
        # ROS publishers
        self.detection_pub = rospy.Publisher('/scout/dog_detection', String, queue_size=1)
        self.photo_pub = rospy.Publisher('/scout/dog_photo', String, queue_size=1)
        
        # ROS subscribers
        self.camera_sub = rospy.Subscriber('/camera/image_raw/compressed', CompressedImage, 
                                         self.camera_callback, queue_size=1)
        
        rospy.loginfo("Dog Detection Module initialized")
    
    def load_room_map(self):
        """Load room boundaries and identification data"""
        # This should be loaded from a configuration file or learned during mapping
        # For now, we'll use estimated room boundaries based on coordinates
        self.room_map = {
            'kitchen': {
                'bounds': {'x_min': 2.5, 'x_max': 4.5, 'y_min': 0.5, 'y_max': 2.5},
                'center': {'x': 3.5, 'y': 1.5}
            },
            'living_room': {
                'bounds': {'x_min': 1.0, 'x_max': 3.0, 'y_min': -3.0, 'y_max': -1.0},
                'center': {'x': 2.0, 'y': -2.0}
            },
            'bedroom': {
                'bounds': {'x_min': -3.0, 'x_max': -1.0, 'y_min': 1.0, 'y_max': 3.0},
                'center': {'x': -2.0, 'y': 2.0}
            },
            'hallway': {
                'bounds': {'x_min': -1.0, 'x_max': 1.0, 'y_min': -1.0, 'y_max': 1.0},
                'center': {'x': 0.0, 'y': 0.0}
            },
            'bathroom': {
                'bounds': {'x_min': -2.0, 'x_max': 0.0, 'y_min': -2.0, 'y_max': 0.0},
                'center': {'x': -1.0, 'y': -1.0}
            }
        }
    
    def setup_detection_model(self):
        """Initialize the dog detection model"""
        if TORCH_AVAILABLE:
            self.setup_torch_model()
        else:
            self.setup_opencv_model()
    
    def setup_torch_model(self):
        """Setup PyTorch-based object detection model"""
        try:
            # Use pre-trained COCO model for object detection
            self.model = detection.fasterrcnn_resnet50_fpn(pretrained=True)
            self.model.eval()
            
            # COCO class labels (class 18 is 'dog')
            self.coco_classes = [
                '__background__', 'person', 'bicycle', 'car', 'motorcycle', 'airplane', 'bus',
                'train', 'truck', 'boat', 'traffic light', 'fire hydrant', 'N/A', 'stop sign',
                'parking meter', 'bench', 'bird', 'cat', 'dog', 'horse', 'sheep', 'cow',
                'elephant', 'bear', 'zebra', 'giraffe', 'N/A', 'backpack', 'umbrella'
            ]
            
            self.dog_class_id = 18  # 'dog' in COCO dataset
            self.detection_method = 'torch'
            
            rospy.loginfo("Using PyTorch Faster R-CNN for dog detection")
            
        except Exception as e:
            rospy.logerr("Failed to initialize PyTorch model: {}".format(e))
            self.setup_opencv_model()
    
    def setup_opencv_model(self):
        """Setup OpenCV-based detection as fallback"""
        try:
            # Download and use Haar cascade for dog detection
            cascade_path = os.path.join(self.photo_dir, 'haarcascade_frontalface_alt.xml')
            
            # In practice, you'd want a proper dog cascade classifier
            # For demo purposes, we'll use a generic animal detection approach
            self.detection_method = 'opencv'
            
            # We'll use background subtraction and contour analysis
            self.bg_subtractor = cv2.createBackgroundSubtractorMOG2(detectShadows=True)
            
            rospy.loginfo("Using OpenCV background subtraction for dog detection")
            
        except Exception as e:
            rospy.logerr("Failed to initialize OpenCV detection: {}".format(e))
            self.detection_method = 'simple'
    
    def camera_callback(self, msg):
        """Process camera images for dog detection"""
        try:
            # Convert ROS image to OpenCV format
            np_arr = np.frombuffer(msg.data, np.uint8)
            image = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            
            if image is None:
                return
            
            # Perform dog detection
            detection_result = self.detect_dog(image)
            
            if detection_result['detected']:
                with self.detection_lock:
                    self.dog_detected = True
                    self.detection_confidence = detection_result['confidence']
                    self.last_detection_time = datetime.now()
                    
                    # Identify current room
                    self.current_room = self.identify_current_room()
                    
                    # Take and save photo
                    photo_path = self.save_dog_photo(image, detection_result)
                    
                    # Publish detection event
                    self.publish_detection_event(photo_path)
                    
                    rospy.loginfo("Dog detected in {} with confidence {:.2f}".format(self.current_room, self.detection_confidence))
            
        except Exception as e:
            rospy.logerr("Error in camera callback: {}".format(e))
    
    def detect_dog(self, image):
        """Detect dogs in the image using the configured method"""
        if self.detection_method == 'torch':
            return self.detect_dog_torch(image)
        elif self.detection_method == 'opencv':
            return self.detect_dog_opencv(image)
        else:
            return self.detect_dog_simple(image)
    
    def detect_dog_torch(self, image):
        """Use PyTorch model for dog detection"""
        try:
            # Preprocess image
            transform = transforms.Compose([
                transforms.ToPILImage(),
                transforms.ToTensor(),
            ])
            
            # Convert BGR to RGB
            image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            input_tensor = transform(image_rgb).unsqueeze(0)
            
            # Run inference
            with torch.no_grad():
                predictions = self.model(input_tensor)
            
            # Process results
            boxes = predictions[0]['boxes'].cpu().numpy()
            labels = predictions[0]['labels'].cpu().numpy()
            scores = predictions[0]['scores'].cpu().numpy()
            
            # Look for dogs (class 18)
            dog_detections = []
            for i, (box, label, score) in enumerate(zip(boxes, labels, scores)):
                if label == self.dog_class_id and score > 0.5:
                    dog_detections.append({
                        'box': box,
                        'confidence': score,
                        'area': (box[2] - box[0]) * (box[3] - box[1])
                    })
            
            if dog_detections:
                # Return the detection with highest confidence
                best_detection = max(dog_detections, key=lambda x: x['confidence'])
                return {
                    'detected': True,
                    'confidence': float(best_detection['confidence']),
                    'bbox': best_detection['box'].tolist(),
                    'method': 'torch'
                }
            else:
                return {'detected': False, 'confidence': 0.0, 'method': 'torch'}
                
        except Exception as e:
            rospy.logerr("PyTorch detection error: {}".format(e))
            return {'detected': False, 'confidence': 0.0, 'method': 'torch'}
    
    def detect_dog_opencv(self, image):
        """Use OpenCV for dog detection"""
        try:
            # Apply background subtraction
            fg_mask = self.bg_subtractor.apply(image)
            
            # Find contours of moving objects
            contours, _ = cv2.findContours(fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            # Filter contours by size (assuming dog-sized objects)
            min_area = 1000  # Minimum area for dog detection
            max_area = 50000  # Maximum area
            
            valid_contours = []
            for contour in contours:
                area = cv2.contourArea(contour)
                if min_area < area < max_area:
                    valid_contours.append(contour)
            
            if valid_contours:
                # Use the largest valid contour as potential dog
                largest_contour = max(valid_contours, key=cv2.contourArea)
                x, y, w, h = cv2.boundingRect(largest_contour)
                
                # Simple heuristics for dog-like shape
                aspect_ratio = w / h
                if 0.5 < aspect_ratio < 2.0:  # Reasonable aspect ratio for a dog
                    confidence = min(0.8, cv2.contourArea(largest_contour) / max_area)
                    return {
                        'detected': True,
                        'confidence': confidence,
                        'bbox': [x, y, x + w, y + h],
                        'method': 'opencv'
                    }
            
            return {'detected': False, 'confidence': 0.0, 'method': 'opencv'}
            
        except Exception as e:
            rospy.logerr("OpenCV detection error: {}".format(e))
            return {'detected': False, 'confidence': 0.0, 'method': 'opencv'}
    
    def detect_dog_simple(self, image):
        """Simple motion-based detection fallback"""
        # This is a very basic fallback that detects any significant motion
        # In practice, you'd want more sophisticated detection
        try:
            if not hasattr(self, 'prev_frame'):
                self.prev_frame = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                return {'detected': False, 'confidence': 0.0, 'method': 'simple'}
            
            current_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            diff = cv2.absdiff(self.prev_frame, current_gray)
            
            # Threshold and count non-zero pixels
            _, thresh = cv2.threshold(diff, 30, 255, cv2.THRESH_BINARY)
            motion_pixels = cv2.countNonZero(thresh)
            
            self.prev_frame = current_gray
            
            # If significant motion detected, assume it might be a dog
            total_pixels = image.shape[0] * image.shape[1]
            motion_ratio = motion_pixels / total_pixels
            
            if motion_ratio > 0.1:  # 10% of image changed
                return {
                    'detected': True,
                    'confidence': min(0.6, motion_ratio * 2),
                    'bbox': [0, 0, image.shape[1], image.shape[0]],
                    'method': 'simple'
                }
            
            return {'detected': False, 'confidence': 0.0, 'method': 'simple'}
            
        except Exception as e:
            rospy.logerr("Simple detection error: {}".format(e))
            return {'detected': False, 'confidence': 0.0, 'method': 'simple'}
    
    def identify_current_room(self):
        """Identify which room the robot is currently in"""
        try:
            current_pose = self.nav_controller.current_pose
            if current_pose is None:
                return "unknown"
            
            x = current_pose.pose.position.x
            y = current_pose.pose.position.y
            
            # Check which room the current position falls into
            for room_name, room_data in self.room_map.items():
                bounds = room_data['bounds']
                if (bounds['x_min'] <= x <= bounds['x_max'] and 
                    bounds['y_min'] <= y <= bounds['y_max']):
                    return room_name
            
            return "unknown"
            
        except Exception as e:
            rospy.logerr("Error identifying room: {}".format(e))
            return "unknown"
    
    def save_dog_photo(self, image, detection_result):
        """Save photo of detected dog"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = "dog_detected_{}_{}.jpg".format(timestamp, self.current_room)
            photo_path = os.path.join(self.photo_dir, filename)
            
            # Draw bounding box if available
            if 'bbox' in detection_result and detection_result['bbox']:
                bbox = detection_result['bbox']
                cv2.rectangle(image, 
                             (int(bbox[0]), int(bbox[1])), 
                             (int(bbox[2]), int(bbox[3])), 
                             (0, 255, 0), 2)
                
                # Add text overlay
                text = "Dog detected ({:.2f})".format(detection_result['confidence'])
                cv2.putText(image, text, (int(bbox[0]), int(bbox[1]) - 10),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            
            # Add room and timestamp info
            cv2.putText(image, "Room: {}".format(self.current_room), (10, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
            cv2.putText(image, timestamp, (10, 70),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            
            # Save image
            cv2.imwrite(photo_path, image)
            
            # Upload if configured
            if self.upload_config['enabled']:
                self.upload_photo(photo_path)
            
            rospy.loginfo("Dog photo saved: {}".format(photo_path))
            return photo_path
            
        except Exception as e:
            rospy.logerr("Error saving photo: {}".format(e))
            return None
    
    def upload_photo(self, photo_path):
        """Upload photo to configured service"""
        try:
            if self.upload_config['service'] == 'local':
                # Just keep local copy
                return photo_path
            
            elif self.upload_config['service'] == 'imgur':
                return self.upload_to_imgur(photo_path)
            
            elif self.upload_config['service'] == 'webhook':
                return self.upload_via_webhook(photo_path)
            
        except Exception as e:
            rospy.logerr("Error uploading photo: {}".format(e))
            return None
    
    def upload_to_imgur(self, photo_path):
        """Upload photo to Imgur"""
        try:
            import base64
            
            with open(photo_path, 'rb') as f:
                image_data = base64.b64encode(f.read())
            
            headers = {'Authorization': 'Client-ID {}'.format(self.upload_config["api_key"])}
            data = {'image': image_data}
            
            response = requests.post('https://api.imgur.com/3/image', 
                                   headers=headers, data=data, timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                imgur_url = result['data']['link']
                rospy.loginfo("Photo uploaded to Imgur: {}".format(imgur_url))
                return imgur_url
            else:
                rospy.logerr("Imgur upload failed: {}".format(response.status_code))
                return None
                
        except Exception as e:
            rospy.logerr("Imgur upload error: {}".format(e))
            return None
    
    def upload_via_webhook(self, photo_path):
        """Upload photo via webhook"""
        try:
            with open(photo_path, 'rb') as f:
                files = {'photo': f}
                data = {
                    'room': self.current_room,
                    'timestamp': datetime.now().isoformat(),
                    'confidence': self.detection_confidence
                }
                
                response = requests.post(self.upload_config['webhook_url'], 
                                       files=files, data=data, timeout=10)
                
                if response.status_code == 200:
                    rospy.loginfo("Photo uploaded via webhook")
                    return response.text
                else:
                    rospy.logerr("Webhook upload failed: {}".format(response.status_code))
                    return None
                    
        except Exception as e:
            rospy.logerr("Webhook upload error: {}".format(e))
            return None
    
    def publish_detection_event(self, photo_path):
        """Publish dog detection event to ROS topics"""
        try:
            detection_msg = String()
            detection_data = {
                'detected': True,
                'room': self.current_room,
                'confidence': self.detection_confidence,
                'timestamp': self.last_detection_time.isoformat(),
                'photo_path': photo_path
            }
            detection_msg.data = json.dumps(detection_data)
            self.detection_pub.publish(detection_msg)
            
            if photo_path:
                photo_msg = String()
                photo_msg.data = photo_path
                self.photo_pub.publish(photo_msg)
            
        except Exception as e:
            rospy.logerr("Error publishing detection event: {}".format(e))
    
    def get_detection_status(self):
        """Get current detection status"""
        with self.detection_lock:
            return {
                'dog_detected': self.dog_detected,
                'current_room': self.current_room,
                'confidence': self.detection_confidence,
                'last_detection': self.last_detection_time.isoformat() if self.last_detection_time else None
            }
    
    def reset_detection(self):
        """Reset detection state"""
        with self.detection_lock:
            self.dog_detected = False
            self.current_room = "unknown"
            self.detection_confidence = 0.0
            self.last_detection_time = None
    
    def start_detection_for_room(self, room_name):
        """Start active dog detection for a specific room"""
        with self.detection_lock:
            self.current_room = room_name
            self.dog_detected = False
            self.detection_confidence = 0.0
        
        rospy.loginfo("Starting dog detection for room: {}".format(room_name))
        
        # Enable camera processing for detection
        self.detection_active = True
    
    def stop_detection(self):
        """Stop active dog detection"""
        with self.detection_lock:
            self.detection_active = False
        
        rospy.loginfo("Dog detection stopped")
    
    def start_continuous_detection(self):
        """Start continuous dog detection (for general monitoring)"""
        self.detection_active = True
        rospy.loginfo("Continuous dog detection started")
    
    def set_room(self, room_name):
        """Set the current room for detection context"""
        with self.detection_lock:
            self.current_room = room_name
