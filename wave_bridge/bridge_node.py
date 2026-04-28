#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from std_msgs.msg import String
from sensor_msgs.msg import Imu 
import serial
import json
import threading
import time
import math

class WaveBridge(Node):
    def __init__(self):
        super().__init__('motor_bridge')
        
        # 1. Open the serial port & establish a lock
        self.ser = serial.Serial('/dev/ttyAMA0', 115200, timeout=0.1)
        self.serial_lock = threading.Lock()
        time.sleep(2) 

        # Parameters
        self.declare_parameter('max_speed', 200)
        self.max_speed = self.get_parameter('max_speed').value

        # Subscribers / Publishers
        self.cmd_vel_sub = self.create_subscription(Twist, 'cmd_vel', self.cmd_vel_callback, 10)
        self.status_pub = self.create_publisher(String, 'rover/status', 10)
        self.imu_pub = self.create_publisher(Imu, 'imu/data_raw', 10)

        self.last_cmd_time = self.get_clock().now()
        self.create_timer(0.5, self.safety_check)

        # timer to request IMU data (20Hz)
        self.create_timer(0.05, self.request_imu_data)

        # Background thread to listen for ESP32 responses
        self.read_thread = threading.Thread(target=self.serial_read_loop, daemon=True)
        self.read_thread.start()

        self.get_logger().info('Wave Bridge active. Polling IMU via Serial.')

    def request_imu_data(self):
        """Sends command {"T": 126} to fetch the latest IMU data."""
        self.send_command({"T": 126})

    def send_command(self, cmd):
        """Send command via locked serial port."""
        def _send():
            try:
                json_str = json.dumps(cmd) + '\n'
                with self.serial_lock:
                    self.ser.write(json_str.encode('utf-8'))
            except Exception as e:
                self.get_logger().error(f"Serial write failed: {e}")
        threading.Thread(target=_send, daemon=True).start()

    def serial_read_loop(self):
        while rclpy.ok():
            try:
                with self.serial_lock:
                    if self.ser.in_waiting > 0:
                        line = self.ser.readline().decode('utf-8').strip()
                        if line:
                            data = json.loads(line)
                            
                            if data.get("T") == 1002:
                                self.publish_imu(
                                    data["ax"], data["ay"], data["az"],
                                    data["gx"], data["gy"], data["gz"]
                                )
            except json.JSONDecodeError:
                continue 
            except Exception as e:
                self.get_logger().error(f"Serial read error: {e}")
            
            time.sleep(0.005) 

    def cmd_vel_callback(self, msg):
        self.last_cmd_time = self.get_clock().now()
        left = int((msg.linear.x - msg.angular.z) * self.max_speed)
        right = int((msg.linear.x + msg.angular.z) * self.max_speed)
        left = max(-255, min(255, left))
        right = max(-255, min(255, right))

        self.send_command({"T": 1, "L": left, "R": right})

    def publish_imu(self, ax, ay, az, gx, gy, gz):
        msg = Imu()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "base_link"

        # CONVERT milli-G's to m/s^2 (ax, ay, az / 1000 * 9.81)
        msg.linear_acceleration.x = (ax / 1000.0) * 9.81
        msg.linear_acceleration.y = (ay / 1000.0) * 9.81
        msg.linear_acceleration.z = (az / 1000.0) * 9.81

        # CONVERT degrees/sec to radians/sec
        msg.angular_velocity.x = math.radians(gx)
        msg.angular_velocity.y = math.radians(gy)
        msg.angular_velocity.z = math.radians(gz)

        # Covariances
        msg.linear_acceleration_covariance = [0.1, 0.0, 0.0, 0.0, 0.1, 0.0, 0.0, 0.0, 0.1]
        msg.angular_velocity_covariance = [0.01, 0.0, 0.0, 0.0, 0.01, 0.0, 0.0, 0.0, 0.01]
        msg.orientation_covariance[0] = -1.0 

        self.imu_pub.publish(msg)

    def safety_check(self):
        elapsed = (self.get_clock().now() - self.last_cmd_time).nanoseconds / 1e9
        if elapsed > 2.0:
            self.send_command({"T": 1, "L": 0, "R": 0})

    def stop(self):
        try:
            with self.serial_lock:
                self.ser.write(b'{"T": 1, "L": 0, "R": 0}\n')
        except:
            pass

def main(args=None):
    rclpy.init(args=args)
    node = WaveBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.stop()
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
