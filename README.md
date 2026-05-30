# Integrated Drone Defense & Situational Awareness System

This project helps detect and stop unknown drones.

Ground cameras find a drone and follow it. The system uses the camera angles to calculate the drone position. The position is shared with TAK, and a defense drone can fly to the target. The defense drone uses its own camera to follow the drone and catch it with a net.

No real keys, certificates, or private demo recordings are stored in this repo.

## Parts

- `drone-vision`: detects and follows drones in video.
- `triangometry-towers-calc`: calculates the drone position from tower cameras.
- `dji-stream-to-tak-bridge`: sends DJI drone data to TAK.
- `takserver`: runs the TAK server for maps and live positions.
