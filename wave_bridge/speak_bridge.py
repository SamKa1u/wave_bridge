import rclpy
from rclpy.node import Node
from std_msgs.msg import Int16MultiArray  # Common msg type for ROS 2 audio

import pvporcupine
import subprocess
import json
import numpy as np
import collections

# File paths
WAKE_MODEL = "/home/sam/wakeword/hey-ro.ppn"  # unresolved
PIPER_MODEL = "/home/sam/wakeword/piper_voices/en_US-amy-medium.onnx"
WHISPER_BIN = "/home/sam/wakeword/whisper.cpp/main"  # unresolved
WHISPER_MODEL = "/home/sam/wakeword/whisper.cpp/models/ggml-tiny.bin"

class VoiceControlNode(Node):
    def __init__(self):
        super().__init__('voice_control_node')
        
        # States
        self.state = {"light": "off", "fan": "off", "door": "locked"}
        
        # Porcupine initialization
        self.porcupine = pvporcupine.create(keyword_paths=[WAKE_MODEL])
        self.frame_length = self.porcupine.frame_length
        
        # Audio buffers
        self.audio_buffer = collections.deque(maxlen=100) # For wake word
        self.stt_recording = False
        self.stt_frames = []
        self.stt_max_frames = (16000 * 5) // self.frame_length  # 5 seconds
        
        # ROS 2 Subscriber for ReSpeaker XVF3800
        # NOTE: Update topic name to match your ReSpeaker driver output
        self.subscription = self.create_subscription(
            Int16MultiArray,
            '/respeaker/audio', 
            self.audio_callback,
            10
        )
        
        self.get_logger().info("Voice Control Node initialized. Listening for wake word...")

    def audio_callback(self, msg):
        # Convert incoming ROS 2 message to numpy array
        pcm_data = np.array(msg.data, dtype=np.int16)
        
        # If the XVF3800 publishes multichannel audio, extract the processed mono channel
        # Example for a 2-channel stream where channel 0 is the clean output:
        # pcm_data = pcm_data[0::2] 
        
        # Process frames of correct length for Porcupine
        for i in range(0, len(pcm_data), self.frame_length):
            frame = pcm_data[i:i + self.frame_length]
            
            if len(frame) < self.frame_length:
                continue

            if not self.stt_recording:
                # Continuous wake word listening
                keyword_index = self.porcupine.process(frame)
                if keyword_index >= 0:
                    self.get_logger().info("Wake word detected!")
                    self.speak("How can I help you?")
                    self.stt_recording = True
                    self.stt_frames = []
            else:
                # Record STT command
                self.stt_frames.extend(frame)
                if len(self.stt_frames) >= self.stt_max_frames * self.frame_length:
                    self.get_logger().info("Finished recording audio.")
                    self.stt_recording = False
                    
                    # Run speech-to-text and execution
                    text = self.run_stt(np.array(self.stt_frames, dtype=np.int16))
                    self.get_logger().info(f"Heard: {text}")
                    
                    intent = self.parse_intent(text)
                    self.execute_intent(intent)
                    self.get_logger().info("Back to wake word listening...")

    def run_stt(self, pcm_data) -> str:
        # Save memory buffer directly to disk for Whisper.cpp
        wav_path = "/tmp/cmd.wav"
        import wave
        with wave.open(wav_path, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2) # 16-bit
            wf.setframerate(16000)
            wf.writeframes(pcm_data.tobytes())

        # Run Whisper.cpp
        result = subprocess.run(
            [WHISPER_BIN, "-m", WHISPER_MODEL, "-f", wav_path, "-nt", "-l", "en", "-oj"],
            capture_output=True, text=True
        )

        try:
            data = json.loads(result.stdout)
            text = "".join(seg["text"] for seg in data["transcription"]["segments"])
            return text.strip().lower()
        except Exception as e:
            self.get_logger().error(f"Whisper parse error: {e}")
            return ""

    def parse_intent(self, text: str):
        if not text: return None
        if "light" in text and "on" in text: return "light_on"
        if "light" in text and "off" in text: return "light_off"
        if "fan" in text and "on" in text: return "fan_on"
        if "fan" in text and "off" in text: return "fan_off"
        if "door" in text and ("lock" in text or "close" in text): return "door_lock"
        if "door" in text and ("unlock" in text or "open" in text): return "door_unlock"
        if "status" in text or "state" in text: return "status_all"
        return None

    def execute_intent(self, intent: str):
        if intent is None:
            self.speak("I didn't understand that.")
            return

        if intent == "light_on":
            self.state["light"] = "on"
            self.speak("Turning the light on.")
        elif intent == "light_off":
            self.state["light"] = "off"
            self.speak("Turning the light off.")
        elif intent == "fan_on":
            self.state["fan"] = "on"
            self.speak("Turning the fan on.")
        elif intent == "fan_off":
            self.state["fan"] = "off"
            self.speak("Turning the fan off.")
        elif intent == "door_lock":
            self.state["door"] = "locked"
            self.speak("Locking the door.")
        elif intent == "door_unlock":
            self.state["door"] = "unlocked"
            self.speak("Unlocking the door.")
        elif intent == "status_all":
            self.speak(
                f"The light is {self.state['light']}, "
                f"the fan is {self.state['fan']}, "
                f"and the door is {self.state['door']}."
            )

    def speak(self, text: str):
        self.get_logger().info(f"Ro Fetch says: {text}")
        p = subprocess.Popen(
            ["piper", "-m", PIPER_MODEL, "--output-raw"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
        p.stdin.write(text.encode("utf-8"))
        p.stdin.close()
       
        aplay = subprocess.Popen(
            ["aplay", "-f", "S16_LE", "-r", "22050"],
            stdin=p.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        p.stdout.close()
        p.wait()
        aplay.wait()

    def destroy_node(self):
        self.porcupine.delete()
        super().destroy_node()

def main(args=None):
    rclpy.init(args=args)
    node = VoiceControlNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()



