#!/usr/bin/env python3
"""
Camera driver and visual odometry for Moorebot Scout
Provides camera feed and enhanced localization through visual features
"""

import rospy
import cv2
import numpy as np
from sensor_msgs.msg import Image, CompressedImage
from geometry_msgs.msg import TwistWithCovarianceStamped
from nav_msgs.msg import Odometry
from cv_bridge import CvBridge
import tf2_ros
import tf2_geometry_msgs
from threading import Lock
import yaml

class ScoutCameraDriver:
    """
    Camera driver with visual odometry capabilities
    """
    
    def __init__(self):
        rospy.init_node('scout_camera_driver', anonymous=True)
        
        # Parameters
        self.device_id = rospy.get_param('~device_id', 0)
        self.frame_id = rospy.get_param('~frame_id', 'camera_link')
        self.width = rospy.get_param('~width', 640)
        self.height = rospy.get_param('~height', 480)
        self.fps = rospy.get_param('~fps', 30)
        self.publish_compressed = rospy.get_param('~compressed', True)
        
        # Initialize OpenCV bridge
        self.bridge = CvBridge()
        
        # Initialize camera
        self.cap = cv2.VideoCapture(self.device_id)
        if not self.cap.isOpened():
            rospy.logerr("Cannot open camera {}".format(self.device_id))
            return
        
        # Set camera properties
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self.cap.set(cv2.CAP_PROP_FPS, self.fps)
        
        # Publishers
        if self.publish_compressed:
            self.image_pub = rospy.Publisher('/camera/image_raw/compressed', 
                                           CompressedImage, queue_size=1)
        else:
            self.image_pub = rospy.Publisher('/camera/image_raw', 
                                           Image, queue_size=1)
        
        self.visual_odom_pub = rospy.Publisher('/visual_odometry', 
                                             TwistWithCovarianceStamped, queue_size=1)
        
        # Visual odometry setup
        self.setup_visual_odometry()
        
        # Thread safety
        self.odom_lock = Lock()
        
        rospy.loginfo("Scout camera driver initialized on device {}".format(self.device_id))
    
    def setup_visual_odometry(self):
        """Initialize visual odometry components"""
        # Feature detector (ORB is fast and works well in various lighting)
        self.detector = cv2.ORB_create(nfeatures=1000)
        
        # Feature matcher
        self.matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        
        # Camera calibration (these should be calibrated for your specific Scout)
        # Default values - should be calibrated properly
        self.camera_matrix = np.array([
            [500.0, 0.0, 320.0],
            [0.0, 500.0, 240.0],
            [0.0, 0.0, 1.0]
        ], dtype=np.float32)
        
        self.dist_coeffs = np.array([0.1, -0.2, 0.0, 0.0, 0.0], dtype=np.float32)
        
        # Previous frame data
        self.prev_frame = None
        self.prev_keypoints = None
        self.prev_descriptors = None
        self.prev_timestamp = None
        
        # Motion tracking
        self.cumulative_motion = np.eye(4)  # 4x4 transformation matrix
        
        rospy.loginfo("Visual odometry initialized")
    
    def process_visual_odometry(self, frame, timestamp):
        """Process visual odometry from camera frames"""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Detect keypoints and descriptors
        keypoints, descriptors = self.detector.detectAndCompute(gray, None)
        
        if (self.prev_frame is not None and 
            descriptors is not None and 
            self.prev_descriptors is not None and
            len(keypoints) > 10 and len(self.prev_keypoints) > 10):
            
            # Match features
            matches = self.matcher.match(self.prev_descriptors, descriptors)
            matches = sorted(matches, key=lambda x: x.distance)
            
            # Use only good matches
            good_matches = matches[:min(50, len(matches))]
            
            if len(good_matches) >= 8:  # Minimum for essential matrix
                # Extract matched points
                pts1 = np.array([self.prev_keypoints[m.queryIdx].pt for m in good_matches])
                pts2 = np.array([keypoints[m.trainIdx].pt for m in good_matches])
                
                # Find essential matrix
                E, mask = cv2.findEssentialMat(
                    pts1, pts2, self.camera_matrix,
                    method=cv2.RANSAC, prob=0.999, threshold=1.0
                )
                
                if E is not None:
                    # Recover pose
                    _, R, t, mask = cv2.recoverPose(
                        E, pts1, pts2, self.camera_matrix, mask=mask
                    )
                    
                    # Calculate time difference
                    dt = (timestamp - self.prev_timestamp).to_sec() if self.prev_timestamp else 0.1
                    
                    if dt > 0:
                        # Convert to velocity (very basic approach)
                        linear_vel = np.linalg.norm(t) / dt
                        angular_vel = np.linalg.norm(cv2.Rodrigues(R)[0]) / dt
                        
                        # Publish visual odometry
                        self.publish_visual_odometry(linear_vel, angular_vel, timestamp)
        
        # Store current frame data
        self.prev_frame = gray.copy()
        self.prev_keypoints = keypoints
        self.prev_descriptors = descriptors
        self.prev_timestamp = timestamp
    
    def publish_visual_odometry(self, linear_vel, angular_vel, timestamp):
        """Publish visual odometry estimate"""
        msg = TwistWithCovarianceStamped()
        msg.header.stamp = timestamp
        msg.header.frame_id = self.frame_id
        
        # Set velocity estimates
        msg.twist.twist.linear.x = linear_vel
        msg.twist.twist.angular.z = angular_vel
        
        # Set covariance (rough estimates - should be tuned)
        msg.twist.covariance[0] = 0.1   # x linear velocity variance
        msg.twist.covariance[35] = 0.1  # z angular velocity variance
        
        self.visual_odom_pub.publish(msg)
    
    def process_frame(self, frame, timestamp):
        """Process a single camera frame"""
        # Apply any image processing here
        processed_frame = frame.copy()
        
        # Visual odometry processing
        self.process_visual_odometry(processed_frame, timestamp)
        
        return processed_frame
    
    def publish_image(self, frame, timestamp):
        """Publish camera image"""
        try:
            if self.publish_compressed:
                # Publish compressed image
                msg = CompressedImage()
                msg.header.stamp = timestamp
                msg.header.frame_id = self.frame_id
                msg.format = "jpeg"
                
                # Compress image
                encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 80]
                result, encimg = cv2.imencode('.jpg', frame, encode_param)
                if result:
                    msg.data = np.array(encimg).tobytes()
                    self.image_pub.publish(msg)
            else:
                # Publish raw image
                msg = self.bridge.cv2_to_imgmsg(frame, "bgr8")
                msg.header.stamp = timestamp
                msg.header.frame_id = self.frame_id
                self.image_pub.publish(msg)
                
        except Exception as e:
            rospy.logwarn("Error publishing image: {}".format(e))
    
    def run(self):
        """Main camera loop"""
        rate = rospy.Rate(self.fps)
        
        while not rospy.is_shutdown():
            ret, frame = self.cap.read()
            if not ret:
                rospy.logwarn("Failed to read frame from camera")
                continue
            
            timestamp = rospy.Time.now()
            
            # Process frame
            processed_frame = self.process_frame(frame, timestamp)
            
            # Publish image
            self.publish_image(processed_frame, timestamp)
            
            rate.sleep()
        
        # Cleanup
        self.cap.release()
        rospy.loginfo("Camera driver shutdown")

def main():
    """Main function"""
    try:
        driver = ScoutCameraDriver()
        driver.run()
    except rospy.ROSInterruptException:
        rospy.loginfo("Scout camera driver shutting down")
    except Exception as e:
        rospy.logerr("Error in scout camera driver: {}".format(e))

if __name__ == '__main__':
    main()
