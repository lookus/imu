# imu
Inertial Measurement Unit

# MPU-9250 Wireless IMU Data Logger

Wireless inertial measurement unit (IMU) data acquisition system using the MPU-9250 
sensor on an ESP32 microcontroller, transmitting 9-axis sensor data (accelerometer, 
gyroscope, magnetometer) and temperature over WiFi via HTTP POST to a Python Flask server.

## Features
- Real-time 9-axis IMU data streaming over WiFi at 20 Hz
- Auto-calibration of accelerometer, gyroscope, and magnetometer on startup
- JSON payload transmission to a Flask REST endpoint
- Server-side CSV logging with in-memory buffer
- REST API endpoints for live data monitoring

## Hardware
- ESP32 Dev Module
- MPU-9250 IMU (I2C, address 0x68)

## Stack
- **Firmware:** Arduino (C++) — FastIMU, ArduinoJson, WiFi, HTTPClient
- **Backend:** Python Flask