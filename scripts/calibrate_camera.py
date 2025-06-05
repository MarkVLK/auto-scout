#!/usr/bin/env python3
"""
Camera calibration script for the Moorebot Scout.
This script helps calibrate the camera for accurate visual odometry.
"""

import cv2
import numpy as np
import os
import pickle
import rospy
from sensor_msgs.msg import Image
from cv_bridge import CvBridge
import yaml

class CameraCalibration:
    def __init__(self):
        """Initialize camera calibration."""
        self.bridge = CvBridge()
        self.camera_matrix = None
        self.dist_coeffs = None
        self.calibrated = False
        
        # Calibration parameters
        self.chessboard_size = (9, 6)  # Inner corners of chessboard
        self.square_size = 0.025  # 25mm squares
        
        # Storage for calibration data
        self.obj_points = []  # 3D points in real world space
        self.img_points = []  # 2D points in image plane
        
        # Prepare object points
        self.obj_point = np.zeros((self.chessboard_size[0] * self.chessboard_size[1], 3), np.float32)
        self.obj_point[:, :2] = np.mgrid[0:self.chessboard_size[0], 0:self.chessboard_size[1]].T.reshape(-1, 2)
        self.obj_point *= self.square_size
        
        # Initialize camera
        self.cap = cv2.VideoCapture(0)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        
        print("Camera calibration initialized")
        print("Chessboard size: {}".format(self.chessboard_size))
        print("Square size: {}m".format(self.square_size))
        print("\nInstructions:")
        print("1. Print a chessboard pattern (9x6 inner corners)")
        print("2. Hold the chessboard at different angles and distances")
        print("3. Press SPACE to capture when corners are detected")
        print("4. Press 'c' to calibrate after capturing enough images")
        print("5. Press 'q' to quit")
        
    def capture_calibration_images(self):
        """Capture images for calibration."""
        images_captured = 0
        
        while True:
            ret, frame = self.cap.read()
            if not ret:
                print("Failed to capture frame")
                break
                
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            
            # Find chessboard corners
            ret_corners, corners = cv2.findChessboardCorners(gray, self.chessboard_size, None)
            
            # Draw corners if found
            if ret_corners:
                cv2.drawChessboardCorners(frame, self.chessboard_size, corners, ret_corners)
                cv2.putText(frame, "Corners detected! Press SPACE to capture", 
                           (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            else:
                cv2.putText(frame, "No corners detected", 
                           (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            
            cv2.putText(frame, "Images captured: {}/20".format(images_captured), 
                       (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.putText(frame, "SPACE: capture, 'c': calibrate, 'q': quit", 
                       (10, frame.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            
            cv2.imshow('Camera Calibration', frame)
            
            key = cv2.waitKey(1) & 0xFF
            
            if key == ord(' ') and ret_corners:
                # Capture image for calibration
                self.obj_points.append(self.obj_point)
                self.img_points.append(corners)
                images_captured += 1
                print("Captured image {}".format(images_captured))
                
            elif key == ord('c'):
                if len(self.obj_points) >= 10:
                    print("Starting calibration...")
                    self.calibrate_camera(gray.shape[::-1])
                    break
                else:
                    print("Need at least 10 images for calibration (have {})".format(len(self.obj_points)))
                    
            elif key == ord('q'):
                break
        
        cv2.destroyAllWindows()
        
    def calibrate_camera(self, image_size):
        """Perform camera calibration."""
        print("Calibrating camera...")
        
        # Calibrate camera
        ret, camera_matrix, dist_coeffs, rvecs, tvecs = cv2.calibrateCamera(
            self.obj_points, self.img_points, image_size, None, None)
        
        if ret:
            self.camera_matrix = camera_matrix
            self.dist_coeffs = dist_coeffs
            self.calibrated = True
            
            # Calculate reprojection error
            total_error = 0
            for i in range(len(self.obj_points)):
                img_points2, _ = cv2.projectPoints(self.obj_points[i], rvecs[i], tvecs[i], 
                                                  camera_matrix, dist_coeffs)
                error = cv2.norm(self.img_points[i], img_points2, cv2.NORM_L2) / len(img_points2)
                total_error += error
            
            mean_error = total_error / len(self.obj_points)
            
            print("Calibration successful!")
            print("Camera matrix:\n{}".format(camera_matrix))
            print("Distortion coefficients:\n{}".format(dist_coeffs))
            print("Mean reprojection error: {:.4f} pixels".format(mean_error))
            
            # Save calibration data
            self.save_calibration()
            
            # Test undistortion
            self.test_undistortion()
            
        else:
            print("Calibration failed!")
            
    def save_calibration(self):
        """Save calibration data to files."""
        calibration_data = {
            'camera_matrix': self.camera_matrix.tolist(),
            'dist_coeffs': self.dist_coeffs.tolist(),
            'image_size': [640, 480]
        }
        
        # Save as YAML for ROS
        config_dir = os.path.join(os.path.dirname(__file__), '..', 'config')
        os.makedirs(config_dir, exist_ok=True)
        
        yaml_file = os.path.join(config_dir, 'camera_calibration.yaml')
        with open(yaml_file, 'w') as f:
            yaml.dump(calibration_data, f)
        
        # Save as pickle for Python
        pickle_file = os.path.join(config_dir, 'camera_calibration.pkl')
        with open(pickle_file, 'wb') as f:
            pickle.dump(calibration_data, f)
        
        print("Calibration data saved to:")
        print("  {}".format(yaml_file))
        print("  {}".format(pickle_file))
        
    def test_undistortion(self):
        """Test camera undistortion with live feed."""
        print("\nTesting undistortion...")
        print("Press any key to exit test")
        
        while True:
            ret, frame = self.cap.read()
            if not ret:
                break
                
            # Undistort image
            undistorted = cv2.undistort(frame, self.camera_matrix, self.dist_coeffs)
            
            # Show comparison
            comparison = np.hstack([frame, undistorted])
            cv2.putText(comparison, "Original", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            cv2.putText(comparison, "Undistorted", (frame.shape[1] + 10, 30), 
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
            
            cv2.imshow('Undistortion Test', comparison)
            
            if cv2.waitKey(1) & 0xFF != 255:
                break
        
        cv2.destroyAllWindows()
        
    def load_calibration(self):
        """Load existing calibration data."""
        config_dir = os.path.join(os.path.dirname(__file__), '..', 'config')
        pickle_file = os.path.join(config_dir, 'camera_calibration.pkl')
        
        if os.path.exists(pickle_file):
            with open(pickle_file, 'rb') as f:
                calibration_data = pickle.load(f)
            
            self.camera_matrix = np.array(calibration_data['camera_matrix'])
            self.dist_coeffs = np.array(calibration_data['dist_coeffs'])
            self.calibrated = True
            
            print("Calibration data loaded successfully")
            print("Camera matrix:\n{}".format(self.camera_matrix))
            print("Distortion coefficients:\n{}".format(self.dist_coeffs))
            return True
        else:
            print("No calibration data found")
            return False
            
    def create_camera_info_msg(self):
        """Create ROS CameraInfo message from calibration data."""
        if not self.calibrated:
            return None
            
        from sensor_msgs.msg import CameraInfo
        
        camera_info = CameraInfo()
        camera_info.header.frame_id = "camera_link"
        camera_info.width = 640
        camera_info.height = 480
        camera_info.distortion_model = "plumb_bob"
        
        # Flatten matrices for ROS message
        camera_info.K = self.camera_matrix.flatten().tolist()
        camera_info.D = self.dist_coeffs.flatten().tolist()
        
        # Identity matrices for R and P (no rectification needed for monocular)
        camera_info.R = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
        camera_info.P = [self.camera_matrix[0,0], 0.0, self.camera_matrix[0,2], 0.0,
                        0.0, self.camera_matrix[1,1], self.camera_matrix[1,2], 0.0,
                        0.0, 0.0, 1.0, 0.0]
        
        return camera_info

def main():
    """Main calibration function."""
    print("Moorebot Scout Camera Calibration")
    print("==================================")
    
    calibration = CameraCalibration()
    
    # Check if calibration already exists
    if calibration.load_calibration():
        print("\nExisting calibration found!")
        choice = input("Do you want to recalibrate? (y/n): ").lower()
        if choice != 'y':
            print("Using existing calibration")
            calibration.test_undistortion()
            return
    
    # Perform calibration
    calibration.capture_calibration_images()
    
    # Clean up
    calibration.cap.release()
    cv2.destroyAllWindows()

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\nCalibration interrupted by user")
    except Exception as e:
        print("Calibration error: {}".format(e))
        import traceback
        traceback.print_exc()
