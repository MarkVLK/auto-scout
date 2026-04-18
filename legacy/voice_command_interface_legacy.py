#!/usr/bin/env python3
"""
Voice command interface for Scout robot
Processes voice commands and converts them to navigation commands
"""

import rospy
import speech_recognition as sr
import pyttsx3
from std_msgs.msg import String
from threading import Thread
import queue
import json

class VoiceCommandInterface:
    """
    Voice command interface for the Scout robot
    """
    
    def __init__(self):
        rospy.init_node('voice_command_interface', anonymous=True)
        
        # Initialize speech recognition
        self.recognizer = sr.Recognizer()
        self.microphone = sr.Microphone()
        
        # Initialize text-to-speech
        self.tts_engine = pyttsx3.init()
        self.tts_engine.setProperty('rate', 150)
        self.tts_engine.setProperty('volume', 0.8)
        
        # Command queue
        self.command_queue = queue.Queue()
        
        # Publishers
        self.command_pub = rospy.Publisher('/scout/command', String, queue_size=1)
        
        # Subscribers
        self.status_sub = rospy.Subscriber('/scout/status', String, self.status_callback)
        
        # Command mapping
        self.command_map = {
            'start patrol': 'start_patrol',
            'begin patrol': 'start_patrol',
            'start patrolling': 'start_patrol',
            'stop patrol': 'stop_patrol',
            'stop patrolling': 'stop_patrol',
            'end patrol': 'stop_patrol',
            'go home': 'go_home',
            'return home': 'go_home',
            'go to kitchen': 'go_kitchen',
            'kitchen': 'go_kitchen',
            'go to living room': 'go_living_room',
            'living room': 'go_living_room',
            'go to bedroom': 'go_bedroom',
            'bedroom': 'go_bedroom',
            'emergency stop': 'emergency_stop',
            'stop now': 'emergency_stop',
            'emergency': 'emergency_stop',
            'reset emergency': 'reset_emergency',
            'reset': 'reset_emergency',
            'save map': 'save_map',
            'save the map': 'save_map'
        }
        
        # Calibrate microphone
        rospy.loginfo("Calibrating microphone for ambient noise...")
        with self.microphone as source:
            self.recognizer.adjust_for_ambient_noise(source)
        rospy.loginfo("Microphone calibrated")
        
        # Start listening thread
        self.listening_thread = Thread(target=self.listen_loop)
        self.listening_thread.daemon = True
        self.listening_thread.start()
        
        # Start command processing thread
        self.processing_thread = Thread(target=self.process_commands)
        self.processing_thread.daemon = True
        self.processing_thread.start()
        
        rospy.loginfo("Voice command interface initialized")
        self.speak("Voice command interface ready")
    
    def speak(self, text):
        """Convert text to speech"""
        try:
            rospy.loginfo("Speaking: {}".format(text))
            self.tts_engine.say(text)
            self.tts_engine.runAndWait()
        except Exception as e:
            rospy.logwarn("TTS error: {}".format(e))
    
    def listen_loop(self):
        """Main listening loop"""
        while not rospy.is_shutdown():
            try:
                # Listen for audio
                with self.microphone as source:
                    rospy.logdebug("Listening for commands...")
                    audio = self.recognizer.listen(source, timeout=1, phrase_time_limit=5)
                
                # Recognize speech
                try:
                    command_text = self.recognizer.recognize_google(audio).lower()
                    rospy.loginfo("Heard: '{}'".format(command_text))
                    
                    # Add to command queue
                    self.command_queue.put(command_text)
                    
                except sr.UnknownValueError:
                    rospy.logdebug("Could not understand audio")
                except sr.RequestError as e:
                    rospy.logwarn("Speech recognition error: {}".format(e))
                
            except sr.WaitTimeoutError:
                # Timeout is normal, continue listening
                pass
            except Exception as e:
                rospy.logwarn("Listening error: {}".format(e))
                rospy.sleep(1)
    
    def process_commands(self):
        """Process recognized commands"""
        while not rospy.is_shutdown():
            try:
                # Get command from queue (blocking)
                command_text = self.command_queue.get(timeout=1)
                
                # Find matching command
                matched_command = None
                for voice_cmd, robot_cmd in self.command_map.items():
                    if voice_cmd in command_text:
                        matched_command = robot_cmd
                        break
                
                if matched_command:
                    rospy.loginfo("Executing command: {}".format(matched_command))
                    self.command_pub.publish(matched_command)
                    
                    # Provide voice feedback
                    if matched_command == 'start_patrol':
                        self.speak("Starting patrol")
                    elif matched_command == 'stop_patrol':
                        self.speak("Stopping patrol")
                    elif matched_command.startswith('go_'):
                        location = matched_command.replace('go_', '').replace('_', ' ')
                        self.speak("Going to {}".format(location))
                    elif matched_command == 'emergency_stop':
                        self.speak("Emergency stop activated")
                    elif matched_command == 'reset_emergency':
                        self.speak("Emergency reset")
                    elif matched_command == 'save_map':
                        self.speak("Saving map")
                else:
                    rospy.loginfo("Unknown command: '{}'".format(command_text))
                    self.speak("I didn't understand that command")
                
            except queue.Empty:
                # Timeout is normal
                continue
            except Exception as e:
                rospy.logwarn("Command processing error: {}".format(e))
    
    def status_callback(self, msg):
        """Handle status updates from the robot"""
        try:
            status = json.loads(msg.data)
            
            # Provide voice feedback for important status changes
            if status.get('emergency_stop', False):
                self.speak("Emergency stop is active")
            elif status.get('battery_level', 100) < 20:
                self.speak("Low battery warning")
            
        except Exception as e:
            rospy.logdebug("Status processing error: {}".format(e))
    
    def run(self):
        """Main run loop"""
        rospy.loginfo("Voice command interface running")
        rospy.spin()

def main():
    """Main function"""
    try:
        interface = VoiceCommandInterface()
        interface.run()
    except rospy.ROSInterruptException:
        rospy.loginfo("Voice command interface shutting down")
    except Exception as e:
        rospy.logerr("Error in voice command interface: {}".format(e))

if __name__ == '__main__':
    main()
