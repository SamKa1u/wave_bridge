from launch import LaunchDescription
from launch_ros.actions import Node, ComposableNodeContainer
from launch_ros.descriptions import ComposableNode
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource 
from ament_index_python.packages import get_package_share_directory
import os

def generate_launch_description():
    # get share directory
    wave_dir = get_package_share_directory('wave_bridge')

    # yaml filepaths
    ekf_path = os.path.join.(wave_dir, 'config', 'ekf.yaml')
    nav2_path = os.path.join.(wave_dir, 'config', 'nav2_params.yaml')



    return LaunchDescription([
        # MOTOR BRIDGE: handles wheel movement and cmd_vel commands
        Node(
            package='wave_bridge',
            executable='motor_bridge',
            name='motor_bridge',
            output='screen'
        ),

        # MODAL BRIDGE: talks to the cloud API for DepthPro
        Node(
            package='wave_bridge',
            executable='modal_bridge',
            name='modal_bridge',
            output='screen'
        ),

        # voice based landmark nav
         Node(
            package='wave_bridge',
            executable='voice_bridge',
            name='voice_bridge',
            output='screen'
        ),


        # robot localization (ekf)
         Node(
            package='robot_localization',
            executable='ekf_node',
            name='ekf_filter_node',
            output='screen',
            parameters=[ekf_path]
        ),


        # nav2 bring up
         IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(nav2_bringup_dir, 'launch','navigation_launch.py')),
            launch_arguments={'params_file': nav2_path, 'use_sim_time': 'false', 'autostart': 'true'}.items()
        ),

        # Physical Mount: 18.7cm left, 15.4 cm up arguments=['--x','0.0','--y', '0.187','--z', '0.154','--yaw' '0','--pitch' '0','--roll', '0', 'base_link', 'camera_link']
        Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            arguments=['--x','0.025','--y', '0.045','--z', '0.0','--yaw' '0','--pitch' '0','--roll', '0', '--frame-id','base_link','--child-frame-id', 'camera_link']
        ),
        # Optical rotation for Z-forward projection
        Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            arguments=['--x','0','--y', '0','--z', '0','--yaw', '-1.571','--pitch', '0','--roll', '-1.571', 'camera_link', 'camera_depth_optical_frame']
        ),

        # DEPTH TO POINTCLOUD
        ComposableNodeContainer(
            name='depth_image_proc_container',
            namespace='',
            package='rclcpp_components',
            executable='component_container',
            composable_node_descriptions=[
                ComposableNode(
                    package='depth_image_proc',
                    plugin='depth_image_proc::PointCloudXyzNode',
                    name='point_cloud_xyz_node',
                    remappings=[
                        ('image_rect', '/camera/depth/image_raw'),
                        ('camera_info', '/camera/depth/camera_info'),
                        ('points', '/camera/depth/points')
                    ]
                ),
            ],
            output='screen',
        ),
        # WEBCAM DRIVER (Logitech C310)
        Node(
            package='usb_cam',
            executable='usb_cam_node_exe',
            name='usb_cam',
            output='screen',
            parameters=[
                {'video_device': '/dev/video0'},
                {'image_width': 1280},
                {'image_height': 720},
                {'pixel_format': 'mjpeg2rgb'}, # C310 supports mjpeg for higher FPS
                {'frame_id': 'camera_link'}
            ]
        ),
    ])

