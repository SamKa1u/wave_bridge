import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from rclpy.callback_groups import ReentrantCallbackGroup
from sensor_msgs.msg import Image, CameraInfo
from cv_bridge import CvBridge
import requests
import numpy as np
import base64
import cv2
import time

class ModalDepthBridge(Node):
    def __init__(self):
        super().__init__('modal_bridge')

        self.modal_url = "https://samka1u--ro-depth-fastapi-app.modal.run/depth"
        self.bridge = CvBridge()
        self.session = requests.Session()
        self.api_busy = False 

        # Crucial for multithreading: allows multiple instances of callbacks to run in parallel
        self.callback_group = ReentrantCallbackGroup()

        self.depth_pub = self.create_publisher(Image, '/camera/depth/image_raw', 10)
        self.info_pub = self.create_publisher(CameraInfo, '/camera/depth/camera_info', 10)

        # Attach the callback group to the subscription
        self.subscription = self.create_subscription(
            Image,
            '/image_raw',
            self.image_callback,
            10,
            callback_group=self.callback_group)

        self.get_logger().info("Modal Depth Bridge started with MultiThreadedExecutor.")

    def get_camera_info(self, header):
        msg = CameraInfo()
        msg.header = header
        msg.height = 720
        msg.width = 1280
        msg.distortion_model = "plumb_bob"
        msg.k = [1280.0, 0.0, 640.0, 
                 0.0, 1280.0, 360.0, 
                 0.0, 0.0, 1.0]
        msg.p = [1280.0, 0.0, 640.0, 0.0, 
                 0.0, 1280.0, 360.0, 0.0, 
                 0.0, 0.0, 1.0, 0.0]
        return msg

    def image_callback(self, msg):
        if self.api_busy == True:
            return

        try:
            self.api_busy = True
            cv_img = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
            _, buffer = cv2.imencode('.jpg', cv_img)
            img_base64 = base64.b64encode(buffer).decode('utf-8')

            start_time = time.time()
            response = self.session.post(
                self.modal_url,
                json={"image": img_base64},
                timeout=30
            )

            if response.status_code == 200:
                depth_data = np.frombuffer(response.content, dtype=np.float32)
                depth_img = depth_data.reshape((720, 1280)) 

                depth_msg = self.bridge.cv2_to_imgmsg(depth_img, encoding="32FC1")
                depth_msg.header.stamp = msg.header.stamp 
                depth_msg.header.frame_id = "camera_depth_optical_frame"
                
                info_msg = self.get_camera_info(depth_msg.header)

                self.depth_pub.publish(depth_msg)
                self.info_pub.publish(info_msg)

                latency = time.time() - start_time
                self.get_logger().info(f"Published depth. Latency: {latency:.3f}s")
            else:
                self.get_logger().error(f"Modal API Error: {response.text}")

        except Exception as e:
            self.get_logger().error(f"Callback failed: {str(e)}")
        
        finally:
            self.api_busy = False

def main(args=None):
    rclpy.init(args=args)
    
    node = ModalDepthBridge()
    
    # Use the MultiThreadedExecutor instead of rclpy.spin()
    # num_threads defaults to the number of CPU cores on your machine
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
