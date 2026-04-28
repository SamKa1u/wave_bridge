import rclpy
from rclpy.node import Node
from tf2_ros import Buffer, TransformListener
from nav2_simple_commander.robot_navigator import BasicNavigator
from geometry_msgs.msg import PoseStamped
import subprocess
import threading
import os
import wave

class LocalVoiceNavManager(Node):
    def __init__(self):
        super().__init__('local_voice_nav')
        
        # ROS2 Nav & Transform Setup
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.navigator = BasicNavigator()
        self.filepath = os.path.expanduser("~/nav_waypoints.json")
        self.saved_landmarks = self.load_landmarks() #	load existing landmarks on boot

        self.whisper_path = "/home/sam/wakeword/whisper.cpp/main"
        self.whisper_model = "/home/sam/wakeword/whisper.cpp/models/ggml-tiny.en.bin"
        self.piper_model = "/home/sam/wakeword/piper_voices/en_US-amy-medium.onnx"
        
        # start voice polling loop
        self.voice_thread = threading.Thread(target=self.audio_capture_loop, daemon=True)
        self.voice_thread.start()
        
        self.say("System active. Ready for voice commands.")
        self.announce_landmarks()
        self.get_logger().info("Local Voice Manager active.")

    def load_landmarks(self):
        """Loads landmarks previously saved to disk"""
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath,'r') as f:
                    landmarks = json.load(f)
                    self.get_logger().info(f"Loaded {len(landmarks)} saved landmarks from file.")
                    return landmarks
            except Exception as e:
                self.get_loger().info("No existing waypoints file found. Starting fresh.")
                return {}
        
    def say(self, text):
        """Generates TTS using Piper and plays it via ALSA."""
        self.get_logger().info(f"Speaking: {text}")
        try:
            # pipe the generated text into piper, outputing raw audio to aplay
            tts_cmd = f"echo '{text}' | piper  --model {self.piper_model} --output_raw | aplay -r 22050 -f S16_LE -t raw"
            subprocess.Popen(tts_cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            self.get_logger().error(f"Piper TTS failed: {e}")

    def announce_landmarks(self):
        """Generates TTS using Piper and plays it via ALSA."""
        if not self.saved_landmarks:
           self.say("No existing waypoints file found. Starting fresh.")

        # join names with comma
        landmark_names = ",".join(self.saved_landmarks.keys())
        self.say(f"The following locations are available: {landmark_names}")

    def audio_capture_loop(self):
        """Records short audio bursts and sends them to Whisper.cpp."""
        # adjust ALSA device index based on `arecord -l` for ReSpeaker
        device = "hw:CARD=Array,DEV=0" 
        temp_audio = "/tmp/voice_cmd.wav"
        
        while rclpy.ok():
            try:
                # record 4 seconds of audio via arecord
                subprocess.run(
                    ["arecord", "-D", device, "-f", "S16_LE", "-c", "1", "-r", "16000", "-d", "4", temp_audio],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
        
                # transcribe using whisper.cpp
                # -nt drops timestamp overhead for faster text extraction
                result = subprocess.run(
                    [self.whisper_path, "-m", self.whisper_model, "-f", temp_audio, "-nt"],
                    capture_output=True, text=True
                )
                
                text = result.stdout.strip().lower()
                
                # cleanup common hallucinations if recording was silent
                if text and not text.isspace() and "thank you" not in text:
                    self.get_logger().info(f"Heard: '{text}'")
                    self.process_command(text)
                    
            except Exception as e:
                self.get_logger().error(f"Voice loop error: {e}")

    def process_command(self, text):
        # trigger point save
        if "create landmark" in text or "save spot as" in text:
            landmark_name = text.split()[-1].strip(".,! ")
            self.create_landmark(landmark_name)
            
        # trigger navigation
        elif "go to" in text or "navigate to" in text:
            landmark_name = text.split()[-1].strip(".,! ")
            self.navigate_to_landmark(landmark_name)

    def create_landmark(self, name):
        try:
            now = rclpy.time.Time()
            trans = self.tf_buffer.lookup_transform('odom', 'base_link', now, rclpy.duration.Duration(seconds=1.0))
            
            self.saved_landmarks[name] = {
                'x': trans.transform.translation.x,
                'y': trans.transform.translation.y
            }
            
            # persist  landmark to disk
            with open(self.filepath,'w')  as f:
                json.dump(self.saved_landmarks, f, indent=4)

            self.say(f"Saved landmark {name}")
            self.get_logger().info(f"Landmark  '{name}' succesfully saved to {self.filepath}")
            
        except Exception as e:
            self.say("Failed to record position.")
            self.get_logger().error(f"TF lookup failed: {e}")

    def navigate_to_landmark(self, name):
        if name not in self.saved_landmarks:
            self.say(f"I do not know where {name} is.")
            return
            
        coords = self.saved_landmarks[name]
        self.say(f"Navigating to {name}")
        
        goal_pose = PoseStamped()
        goal_pose.header.frame_id = 'odom'
        goal_pose.header.stamp = self.navigator.get_clock().now().to_msg()
        goal_pose.pose.position.x = coords['x']
        goal_pose.pose.position.y = coords['y']
        goal_pose.pose.orientation.w = 1.0 
        
        self.navigator.goToPose(goal_pose)

def main(args=None):
    rclpy.init(args=args)
    node = LocalVoiceNavManager()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
