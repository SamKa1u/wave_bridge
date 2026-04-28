from setuptools import find_packages, setup

package_name = 'wave_bridge'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/config', ['config/nav2_params.yaml','config/ekf.yaml']),
        ('share/' + package_name + '/launch', ['launch/ro_launch.py']),

    ],
    package_data={'': ['py.typed']},
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='sam',
    maintainer_email='sam@todo.todo',
    description='WaveRover bridge  for ros',
    license='MIT',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
             'motor_bridge = wave_bridge.bridge_node:main',
             'modal_bridge = wave_bridge.modal_bridge:main',
             'voice_bridge = wave_bridge.landmark_bridge:main',
        ],
    },
)
