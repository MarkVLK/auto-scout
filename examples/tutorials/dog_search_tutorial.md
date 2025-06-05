# Auto-Scout Tutorial: Getting Started with Dog Search

This tutorial will guide you through setting up and using the dog search functionality of your Auto-Scout robot.

## Prerequisites

- Moorebot Scout robot with FHL-LD19 Lidar
- Ubuntu 20.04 with ROS Noetic installed
- Auto-Scout software installed and configured
- Robot mapped your house layout

## Step 1: Verify System Setup

First, ensure your robot is properly set up:

```bash
# Check ROS is running
roscore &

# Verify Lidar connection
rostopic echo /scan

# Check camera feed
rostopic echo /camera/image_raw/compressed

# Test navigation system
roslaunch auto-scout navigation.launch
```

## Step 2: Configure Room Layout

Edit your configuration file to match your house layout:

```bash
nano ~/catkin_ws/src/auto-scout/config/scout_config.yaml
```

Update the `house_layout` section with your room coordinates:

```yaml
house_layout:
  rooms:
    living_room:
      center: {x: 2.0, y: -2.0}
      bounds: {x_min: 1.0, x_max: 3.0, y_min: -3.0, y_max: -1.0}
      waypoints:
        - {x: 1.5, y: -1.5}
        - {x: 2.5, y: -2.5}
    
    kitchen:
      center: {x: 3.5, y: 1.5}
      # ... add your actual coordinates
```

## Step 3: Start the Complete System

Launch all Auto-Scout components:

```bash
roslaunch auto-scout scout_complete.launch
```

This will start:
- Navigation controller
- Dog detection module
- Web interface
- Voice command interface
- All sensor drivers

## Step 4: Using Dog Search

### Method 1: Voice Commands

Simply say one of these phrases:
- "Find my dog"
- "Find dog" 
- "Search for dog"

To stop the search:
- "Stop searching"
- "Stop dog search"

### Method 2: Web Interface

1. Open browser to: `http://your-robot-ip:8080`
2. Click "Find Dog" button
3. Monitor progress on the dashboard
4. View results when search completes

### Method 3: ROS Commands

```bash
# Start dog search
rostopic pub /scout/command std_msgs/String "find_dog"

# Stop dog search  
rostopic pub /scout/command std_msgs/String "stop_dog_search"

# Monitor status
rostopic echo /scout/status
```

## Step 5: Understanding the Search Process

When you start a dog search, the robot will:

1. **Activate Search Mode**: Pauses normal patrol operations
2. **Plan Route**: Determines optimal path through rooms
3. **Visit Each Room**: Goes to each room in configured order
4. **Search Room**: Spends 30 seconds detecting in each room
5. **Take Photo**: Captures image if dog is detected
6. **Record Location**: Notes which room dog was found in
7. **Return Home**: Automatically goes back to charging dock
8. **Report Results**: Updates status with search results

## Step 6: Monitoring Search Progress

### Web Dashboard
The web interface shows:
- Current search status
- Which room is being searched
- Progress through room list
- Final results and photos

### ROS Topics
Monitor these topics for detailed information:

```bash
# Overall robot status
rostopic echo /scout/status

# Dog detection events
rostopic echo /scout/dog_detection

# Photo capture events  
rostopic echo /scout/dog_photo

# Navigation status
rostopic echo /move_base/status
```

### Log Files
Check system logs:

```bash
# Main system log
tail -f /var/log/scout/scout.log

# ROS logs
tail -f ~/.ros/log/latest/rosout.log
```

## Step 7: Customizing Search Parameters

Edit configuration to customize search behavior:

```yaml
dog_search:
  max_search_time: 600     # Total time limit (10 minutes)
  room_search_time: 30     # Time per room (30 seconds)
  detection_confidence: 0.7 # Detection threshold
  
  search_order:            # Customize room order
    - "living_room"
    - "kitchen"
    - "bedroom"
    # Add/remove/reorder as needed
```

## Step 8: Troubleshooting

### Common Issues

**Robot doesn't respond to voice commands:**
```bash
# Check microphone
arecord -l

# Test voice recognition
rostopic echo /voice_commands

# Restart voice interface
sudo systemctl restart scout-voice
```

**Dog detection not working:**
```bash
# Check camera
rostopic echo /camera/image_raw/compressed

# Test detection module
python3 src/dog_detection_module.py

# Check detection confidence in logs
grep "detection" ~/.ros/log/latest/rosout.log
```

**Navigation issues:**
```bash
# Check Lidar
rostopic echo /scan

# Verify map
rosrun map_server map_saver -f test_map

# Check localization
rostopic echo /amcl_pose
```

**Search gets stuck in room:**
```bash
# Check waypoints in config
# Verify room boundaries are correct
# Test manual navigation to room
rostopic pub /move_base_simple/goal geometry_msgs/PoseStamped ...
```

### Recovery Procedures

**Emergency stop during search:**
- Say "Emergency stop" or press emergency button
- Robot will halt immediately
- Resume with "Find dog" when ready

**Search timeout:**
- Robot automatically returns to dock after 10 minutes
- Check logs for any errors
- Verify room waypoints are reachable

**False detections:**
- Adjust detection confidence in config
- Check lighting conditions in rooms
- Verify camera calibration

## Step 9: Advanced Usage

### Custom Room Order
Edit search order based on where your dog usually hangs out:

```yaml
search_order:
  - "bedroom"      # Check dog's favorite spot first
  - "living_room"  
  - "kitchen"
  # ... other rooms
```

### Photo Management
Configure where photos are saved:

```yaml
photo_upload:
  enabled: true
  service: "local"
  local_path: "~/scout_photos"
  webhook_url: "http://your-server/webhook"  # Optional notifications
```

### Integration with Smart Home
Send notifications when dog is found:

```bash
# Example webhook payload when dog found:
{
  "event": "dog_found",
  "room": "kitchen", 
  "timestamp": "2025-06-04T10:30:00Z",
  "photo_url": "http://robot-ip/photos/dog_20250604_103000.jpg"
}
```

## Conclusion

Your Auto-Scout robot is now ready to help find your dog! The system provides multiple ways to initiate searches and comprehensive monitoring of the search process. 

For additional help:
- Check the main README.md
- Review log files for detailed diagnostics  
- Use the web interface for real-time monitoring
- Customize configuration for your specific house layout

Happy dog finding! 🐕🤖
