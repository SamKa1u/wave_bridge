import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from rclpy.callback_groups import ReentrantCallbackGroup
from sensor_msgs.msg import Image, CameraInfo
from std_msgs.msg import String
from cv_bridge import CvBridge
import requests
import numpy as np
import base64
import cv2
import time

class ModalDepthBridge(Node):
    def __init__(self):
        super().__init__('modal_bridge')
        self.base_url = "https://samka1u--ro-depth-fastapi-app.modal.run"
        self.bridge = CvBridge()
        self.session = requests.Session()
        self.api_busy = False
        self.latest_msg = None 
        self.last_trigger_time = 0.0  
        
        self.callback_group = ReentrantCallbackGroup()
        
        self.depth_pub = self.create_publisher(Image, '/camera/depth/image_raw', 10)
        self.info_pub = self.create_publisher(CameraInfo, '/camera/depth/camera_info', 10)
        self.scene_pub = self.create_publisher(String, '/voice/scene', 10)

        self.subscription = self.create_subscription(
            Image, '/image_raw', self.image_callback, 10, callback_group=self.callback_group)
        
        self.voice_sub = self.create_subscription(
            String, '/voice/transcription', self.voice_callback, 10, callback_group=self.callback_group)

        self.get_logger().info("Bridge Online. Depth streaming; Voice description (5s cooldown) active.")

    def get_camera_info(self, header):
        msg = CameraInfo()
        msg.header = header
        msg.height = 720
        msg.width = 1280
        msg.distortion_model = "plumb_bob"
        msg.k = [1280.0, 0.0, 640.0, 0.0, 1280.0, 360.0, 0.0, 0.0, 1.0]
        msg.p = [1280.0, 0.0, 640.0, 0.0, 0.0, 1280.0, 360.0, 0.0, 0.0, 0.0, 1.0, 0.0]
        return msg

    def voice_callback(self, msg):
        current_time = time.time()
        if "what do you see" in msg.data.lower():
            # Cooldown check: 5 seconds since the phrase was first heard
            if current_time - self.last_trigger_time > 5.0:
                if self.latest_msg is not None:
                    # Update timer IMMEDIATELY upon hearing the phrase
                    self.last_trigger_time = current_time
                    self.get_logger().info("Phrase heard! Cooldown started. Requesting description...")
                    self.get_description(self.latest_msg)
                else:
                    self.get_logger().warn("Heard command, but image buffer is empty.")
            else:
                remaining = 5.0 - (current_time - self.last_trigger_time)
                self.get_logger().info(f"Ignoring repeat command. Cooldown active for {remaining:.1f}s.")

    def get_description(self, msg):
        """Task runs in a separate thread via MultiThreadedExecutor."""
        try:
            cv_img = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
            _, buffer = cv2.imencode('.jpg', cv_img)
            img_payload = {"image": base64.b64encode(buffer).decode('utf-8')}

            response = self.session.post(f"{self.base_url}/description", json=img_payload, timeout=15)
            if response.status_code == 200:
                scene_msg = String()
                scene_msg.data = response.text  # Plain text from API
                self.scene_pub.publish(scene_msg)
                self.get_logger().info(f"Published Scene Description: {response.text}")
            else:
                self.get_logger().error(f"Description API Error: {response.status_code}")
        except Exception as e:
            self.get_logger().error(f"Async description failed: {str(e)}")

    def image_callback(self, msg):
        self.latest_msg = msg
        
        if self.api_busy:
            return

        try:
            self.api_busy = True
            cv_img = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
            _, buffer = cv2.imencode('.jpg', cv_img)
            img_payload = {"image": base64.b64encode(buffer).decode('utf-8')}

            depth_res = self.session.post(f"{self.base_url}/depth", json=img_payload, timeout=10)
            if depth_res.status_code == 200:
                depth_data = np.frombuffer(depth_res.content, dtype=np.float32)
                depth_img = depth_data.reshape((720, 1280))
                depth_msg = self.bridge.cv2_to_imgmsg(depth_img, encoding="32FC1")
                depth_msg.header = msg.header
                depth_msg.header.frame_id = "camera_depth_optical_frame"
                
                self.depth_pub.publish(depth_msg)
                self.info_pub.publish(self.get_camera_info(depth_msg.header))

        except Exception as e:
            self.get_logger().error(f"Depth loop error: {str(e)}")
        finally:
            self.api_busy = False

def main(args=None):
    rclpy.init(args=args)
    node = ModalDepthBridge()
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
