# Log Staging Service | 日志暂存服务器

English | [中文](README.md)

## Project Overview

The Log Staging Service is a Python-based HTTP server designed for receiving, processing, and distributing system log files. It provides comprehensive functionality for log upload, processing, download, and management, with specialized decompression services for protocol stack logs.

## Core Features

### 📤 Log Upload
- Support uploading tar.gz log packages via PUT/POST methods
- Intelligent log type recognition and corresponding processing

### 📋 Log Management
- Intuitive web interface displaying log lists
- Support for batch selection and operations (delete, download)
- Real-time file information display (name, size, creation time)
- Smart tagging system (Protocol Stack Logs, OAM & Antenna Logs)

### 🔄 Protocol Stack Log Processing
- Automatic recognition of log packages containing "stack" keyword
- Dedicated tool invocation for decompressing proprietary protocol stack logs
- Asynchronous processing with real-time progress display
- Generation of human-readable text format logs

### 📊 Log Details
- Dedicated log detail pages supporting URL sharing
- Reserved AI analysis functionality interface
- Complete log metadata display

### 🗂️ Automatic Cleanup
- Intelligent storage management: retain logs for 1 month by default
- Automatic cleanup when space is insufficient: keep only the most recent week's logs
- Disk space threshold: 100GB

## Technical Features

- 🐳 **Docker Containerization**: Complete Docker deployment solution
- 🎨 **Modern UI**: Clean and beautiful web interface
- ⚡ **Asynchronous Processing**: Large file processing doesn't block user operations
- 🔧 **Quick Deployment**: Provides deploy.sh, restart.sh, stop.sh scripts

## Quick Start

### Deploy with Docker

```bash
# Build and start service
./deploy.sh

# Restart service
./restart.sh

# Stop service
./stop.sh
```

### Manual Deployment

```bash
# Install dependencies
pip install -r requirements.txt

# Start service
python app.py
```

## System Requirements

- Python 3.8+
- Docker (recommended)
- Disk space: At least 100GB available space
- tool_log_decompress tool (for protocol stack log decompression)

## Configuration

Main configuration items:
- Log storage path
- Processing thread count (default 14)
- Automatic cleanup policy
- Service port configuration

## API Endpoints

### Upload Log
```http
PUT /upload
POST /upload
Content-Type: multipart/form-data
```

### Download Log
```http
GET /download/<log_id>
```

### Log List
```http
GET /logs
```

## Contributing

We welcome Issues and Pull Requests to improve this project.

## License

[License Information]

## Contact

[Contact Information]
