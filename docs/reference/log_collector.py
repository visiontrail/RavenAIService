#!/usr/bin/env python3
"""
Log Collector for Satellite Base Station System

This module provides functionality to collect logs from various components:
- OAM logs from main control board and baseband cards
- Protocol stack logs (STACK_CUCP, STACK_CUUP, STACK_DU)
- Support for both local and remote (SFTP) log collection
"""

import os
import sys
import time
import logging
import tarfile
import tempfile
import shutil
import glob
import paramiko
from typing import List, Dict, Optional, Tuple, Union
from datetime import datetime
import json

# Configure logging
logger = logging.getLogger(__name__)

class LogCollector:
    """
    Log collector for satellite base station system
    
    Supports collecting logs from:
    - Main control board (local access)
    - Baseband cards (SFTP access)
    - Different software components (OAM, STACK_CUCP, STACK_CUUP, STACK_DU)
    """
    
    # Hardware mapping: processFlag -> IP address
    HARDWARE_MAPPING = {
        'BPO1-D2000_1': '172.77.245.112',
        'BPO1-D2000_3': '172.77.245.113', 
        'BPO3-D2000_1': '172.77.245.118'
    }
    
    # Logical mapping: processFlag -> IP address
    LOGICAL_MAPPING = {
        'CUUP_OAM': '172.77.245.112',
        'STACK_CUUP': '172.77.245.112',
        'DU_OAM': '172.77.245.113',
        'STACK_DU': '172.77.245.113',
        'DVB_OAM': '172.77.245.118'
    }
    
    # Software component definitions
    SOFTWARE_COMPONENTS = {
        'STACK_CUCP': {
            'location': 'local',
            'log_path': '/tmp/tmpfs/log/gnb_cucp/gnb_cucp-{timestamp}/',
            'type': 'stack'
        },
        'CUUP_OAM': {
            'location': 'remote',
            'ip': '172.77.245.112',
            'log_path': '/tmp/oam/log/',
            'type': 'oam'
        },
        'STACK_CUUP': {
            'location': 'remote',
            'ip': '172.77.245.112',
            'log_path': '/tmp/tmpfs/log/gnb_cuup/gnb_cuup-{timestamp}/',
            'type': 'stack'
        },
        'DU_OAM': {
            'location': 'remote',
            'ip': '172.77.245.113',
            'log_path': '/tmp/oam/log/',
            'type': 'oam'
        },
        'STACK_DU': {
            'location': 'remote',
            'ip': '172.77.245.113',
            'log_path': '/tmp/tmpfs/log/gnb_du/gnb_du-{timestamp}/',
            'type': 'stack'
        },
        'DVB_OAM': {
            'location': 'remote',
            'ip': '172.77.245.118',
            'log_path': '/tmp/oam/log/',
            'type': 'oam'
        },
        'MAIN_OAM': {
            'location': 'local',
            'log_path': '/tmp/oam/log/',
            'type': 'oam'
        }
    }
    
    # Hardware to software mapping
    HARDWARE_TO_SOFTWARE = {
        'BPO1-D2000_1': ['CUUP_OAM', 'STACK_CUUP'],
        'BPO1-D2000_3': ['DU_OAM', 'STACK_DU'],
        'BPO3-D2000_1': ['DVB_OAM']
    }
    
    def __init__(self, sftp_username: str = 'root', sftp_password: str = 'root'):
        """
        Initialize log collector
        
        Args:
            sftp_username: Username for SFTP connections
            sftp_password: Password for SFTP connections
        """
        self.sftp_username = sftp_username
        self.sftp_password = sftp_password
        self.temp_dir = None
        self.collected_logs = []
        
    def _create_temp_directory(self) -> str:
        """Create temporary directory for log collection"""
        if self.temp_dir is None:
            self.temp_dir = tempfile.mkdtemp(prefix='log_collection_')
            logger.info(f"Created temporary directory: {self.temp_dir}")
        return self.temp_dir
    
    def _cleanup_temp_directory(self):
        """Clean up temporary directory"""
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
            logger.info(f"Cleaned up temporary directory: {self.temp_dir}")
            self.temp_dir = None
    
    def _create_sftp_connection(self, ip_address: str) -> Tuple[paramiko.SSHClient, paramiko.SFTPClient]:
        """
        Create SFTP connection to remote host
        
        Args:
            ip_address: IP address of remote host
            
        Returns:
            Tuple of (SSH client, SFTP client)
            
        Raises:
            Exception: If connection fails
        """
        try:
            ssh_client = paramiko.SSHClient()
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            logger.info(f"Connecting to {ip_address} via SFTP...")
            ssh_client.connect(
                hostname=ip_address,
                username=self.sftp_username,
                password=self.sftp_password,
                timeout=30
            )
            
            sftp_client = ssh_client.open_sftp()
            logger.info(f"SFTP connection established to {ip_address}")
            
            return ssh_client, sftp_client
            
        except Exception as e:
            logger.error(f"Failed to connect to {ip_address}: {str(e)}")
            raise
    
    def _find_timestamped_directories(self, sftp_client: paramiko.SFTPClient, base_path: str) -> List[str]:
        """
        Find directories with timestamp pattern in remote path
        
        Args:
            sftp_client: SFTP client
            base_path: Base path to search (without timestamp part)
            
        Returns:
            List of found directory paths
        """
        try:
            # Extract the parent directory and pattern
            parent_dir = os.path.dirname(base_path.rstrip('/'))
            pattern_name = os.path.basename(base_path.rstrip('/'))
            
            # Remove the {timestamp} placeholder to get the prefix
            if '{timestamp}' in pattern_name:
                prefix = pattern_name.split('{timestamp}')[0]
            else:
                return [base_path]  # No timestamp pattern, return as-is
            
            logger.debug(f"Searching for directories matching pattern '{prefix}*' in {parent_dir}")
            
            # List directories in parent directory
            try:
                entries = sftp_client.listdir_attr(parent_dir)
            except FileNotFoundError:
                logger.warning(f"Directory not found: {parent_dir}")
                return []
            
            # Find matching directories
            matching_dirs = []
            for entry in entries:
                if entry.filename.startswith(prefix) and entry.st_mode and (entry.st_mode & 0o040000):  # Check if it's a directory
                    full_path = os.path.join(parent_dir, entry.filename)
                    matching_dirs.append(full_path)
                    logger.debug(f"Found matching directory: {full_path}")
            
            return sorted(matching_dirs)  # Sort to get most recent first
            
        except Exception as e:
            logger.error(f"Error finding timestamped directories in {base_path}: {str(e)}")
            return []
    
    def _collect_local_logs(self, log_path: str, component_name: str, current_time: str) -> bool:
        """
        Collect logs from local filesystem
        
        Args:
            log_path: Path to log directory
            component_name: Name of the component
            current_time: Current time string for timestamp replacement
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Replace timestamp placeholder if present
            if '{timestamp}' in log_path:
                # For local logs, we need to find directories matching the pattern
                base_path = log_path.replace('{timestamp}', '*')
                matching_dirs = glob.glob(base_path)
                
                if not matching_dirs:
                    logger.warning(f"No directories found matching pattern: {base_path}")
                    return False
                
                # Use the most recent directory (assuming timestamp sorting)
                actual_log_path = sorted(matching_dirs)[-1]
                logger.info(f"Using most recent log directory: {actual_log_path}")
            else:
                actual_log_path = log_path
            
            if not os.path.exists(actual_log_path):
                logger.warning(f"Local log path does not exist: {actual_log_path}")
                return False
            
            # Create component directory in temp directory
            temp_dir = self._create_temp_directory()
            component_dir = os.path.join(temp_dir, component_name)
            os.makedirs(component_dir, exist_ok=True)
            
            # Copy all files from log directory
            files_copied = 0
            for root, dirs, files in os.walk(actual_log_path):
                for file in files:
                    src_file = os.path.join(root, file)
                    # Maintain directory structure
                    rel_path = os.path.relpath(src_file, actual_log_path)
                    dst_file = os.path.join(component_dir, rel_path)
                    
                    # Create destination directory if needed
                    dst_dir = os.path.dirname(dst_file)
                    os.makedirs(dst_dir, exist_ok=True)
                    
                    # Copy file
                    shutil.copy2(src_file, dst_file)
                    files_copied += 1
            
            logger.info(f"Collected {files_copied} files from {component_name} (local: {actual_log_path})")
            self.collected_logs.append({
                'component': component_name,
                'location': 'local',
                'path': actual_log_path,
                'files_count': files_copied
            })
            
            return files_copied > 0
            
        except Exception as e:
            logger.error(f"Error collecting local logs for {component_name}: {str(e)}")
            return False
    
    def _collect_remote_logs(self, ip_address: str, log_path: str, component_name: str, current_time: str) -> bool:
        """
        Collect logs from remote host via SFTP
        
        Args:
            ip_address: IP address of remote host
            log_path: Path to log directory on remote host
            component_name: Name of the component
            current_time: Current time string for timestamp replacement
            
        Returns:
            True if successful, False otherwise
        """
        ssh_client = None
        sftp_client = None
        
        try:
            # Establish SFTP connection
            ssh_client, sftp_client = self._create_sftp_connection(ip_address)
            
            # Handle timestamp patterns in path
            if '{timestamp}' in log_path:
                matching_dirs = self._find_timestamped_directories(sftp_client, log_path)
                if not matching_dirs:
                    logger.warning(f"No directories found matching pattern: {log_path}")
                    return False
                
                # Use the most recent directory
                actual_log_path = sorted(matching_dirs)[-1]
                logger.info(f"Using most recent remote log directory: {actual_log_path}")
            else:
                actual_log_path = log_path
            
            # Check if remote path exists
            try:
                sftp_client.stat(actual_log_path)
            except FileNotFoundError:
                logger.warning(f"Remote log path does not exist: {actual_log_path}")
                return False
            
            # Create component directory in temp directory
            temp_dir = self._create_temp_directory()
            component_dir = os.path.join(temp_dir, component_name)
            os.makedirs(component_dir, exist_ok=True)
            
            # Download all files from remote directory
            files_downloaded = self._download_directory_recursive(sftp_client, actual_log_path, component_dir)
            
            logger.info(f"Collected {files_downloaded} files from {component_name} (remote: {ip_address}:{actual_log_path})")
            self.collected_logs.append({
                'component': component_name,
                'location': 'remote',
                'ip': ip_address,
                'path': actual_log_path,
                'files_count': files_downloaded
            })
            
            return files_downloaded > 0
            
        except Exception as e:
            logger.error(f"Error collecting remote logs for {component_name} from {ip_address}: {str(e)}")
            return False
        finally:
            # Clean up connections
            if sftp_client:
                sftp_client.close()
            if ssh_client:
                ssh_client.close()
    
    def _download_directory_recursive(self, sftp_client: paramiko.SFTPClient, remote_dir: str, local_dir: str) -> int:
        """
        Recursively download directory from remote host
        
        Args:
            sftp_client: SFTP client
            remote_dir: Remote directory path
            local_dir: Local directory path
            
        Returns:
            Number of files downloaded
        """
        files_downloaded = 0
        
        try:
            # List remote directory contents
            entries = sftp_client.listdir_attr(remote_dir)
            
            for entry in entries:
                remote_path = os.path.join(remote_dir, entry.filename)
                local_path = os.path.join(local_dir, entry.filename)
                
                if entry.st_mode and (entry.st_mode & 0o040000):  # Directory
                    # Create local directory and recurse
                    os.makedirs(local_path, exist_ok=True)
                    files_downloaded += self._download_directory_recursive(sftp_client, remote_path, local_path)
                else:  # File
                    # Download file
                    sftp_client.get(remote_path, local_path)
                    files_downloaded += 1
                    logger.debug(f"Downloaded: {remote_path} -> {local_path}")
            
        except Exception as e:
            logger.error(f"Error downloading directory {remote_dir}: {str(e)}")
        
        return files_downloaded
    
    def _create_archive(self, current_time: str, output_dir: str) -> Optional[str]:
        """
        Create compressed archive of collected logs
        
        Args:
            current_time: Current time string for filename
            output_dir: Directory to save the archive
            
        Returns:
            Path to created archive, or None if failed
        """
        try:
            if not self.temp_dir or not os.path.exists(self.temp_dir):
                logger.error("No logs collected to archive")
                return None
            
            # Determine archive name based on actual collected components
            collected_components = [log['component'] for log in self.collected_logs]
            
            # Convert component names to lowercase and sort for consistent naming
            name_parts = sorted([component.lower() for component in collected_components])
            
            if not name_parts:
                name_parts.append('logs')
            
            # Create filename with timestamp
            timestamp = datetime.strptime(current_time, '%Y-%m-%d %H:%M:%S').strftime('%Y%m%d%H%M%S')
            filename = f"{'_'.join(name_parts)}_{timestamp}.tgz"
            
            # Ensure output directory exists
            os.makedirs(output_dir, exist_ok=True)
            
            # Create archive
            archive_path = os.path.join(output_dir, filename)
            with tarfile.open(archive_path, 'w:gz') as tar:
                # Add all collected logs to archive
                for item in os.listdir(self.temp_dir):
                    item_path = os.path.join(self.temp_dir, item)
                    tar.add(item_path, arcname=item)
            
            # Get archive size
            archive_size = os.path.getsize(archive_path)
            
            logger.info(f"Created log archive: {archive_path} ({archive_size} bytes)")
            
            return archive_path
            
        except Exception as e:
            logger.error(f"Error creating archive: {str(e)}")
            return None
    
    def collect_logs_by_hardware(self, hardware_list: List[str], current_time: str, output_dir: str = '/opt/soft/Satellite_McpServer/ftp_data/logs') -> Dict:
        """
        Collect logs by hardware board
        
        Args:
            hardware_list: List of hardware board names (e.g., ['BPO1-D2000_1', 'BPO3-D2000_1'])
            current_time: Current time string (format: 'YYYY-MM-DD HH:MM:SS')
            output_dir: Output directory for archive
            
        Returns:
            Dictionary with collection results
        """
        try:
            logger.info(f"Starting log collection for hardware: {hardware_list}")
            
            # Reset collection state
            self.collected_logs = []
            self._cleanup_temp_directory()
            
            # Collect logs for each hardware board
            for hardware in hardware_list:
                if hardware not in self.HARDWARE_TO_SOFTWARE:
                    logger.warning(f"Unknown hardware board: {hardware}")
                    continue
                
                logger.info(f"Collecting logs for hardware board: {hardware}")
                
                # Get software components for this hardware
                software_components = self.HARDWARE_TO_SOFTWARE[hardware]
                
                for component in software_components:
                    if component not in self.SOFTWARE_COMPONENTS:
                        logger.warning(f"Unknown software component: {component}")
                        continue
                    
                    comp_info = self.SOFTWARE_COMPONENTS[component]
                    
                    if comp_info['location'] == 'local':
                        self._collect_local_logs(comp_info['log_path'], component, current_time)
                    else:
                        self._collect_remote_logs(comp_info['ip'], comp_info['log_path'], component, current_time)
            
            # Create archive
            archive_path = self._create_archive(current_time, output_dir)
            
            # Prepare result
            result = {
                'status': 'success' if archive_path else 'partial_success',
                'archive_path': archive_path,
                'collected_logs': self.collected_logs,
                'total_components': len(self.collected_logs),
                'timestamp': current_time
            }
            
            if not archive_path:
                result['status'] = 'error'
                result['message'] = 'Failed to create archive'
            
            return result
            
        except Exception as e:
            logger.error(f"Error in collect_logs_by_hardware: {str(e)}")
            return {
                'status': 'error',
                'message': str(e),
                'collected_logs': self.collected_logs,
                'timestamp': current_time
            }
        finally:
            self._cleanup_temp_directory()
    
    def collect_logs_by_software(self, software_list: List[str], current_time: str, output_dir: str = '/opt/soft/Satellite_McpServer/ftp_data/logs') -> Dict:
        """
        Collect logs by software component
        
        Args:
            software_list: List of software component names (e.g., ['STACK_CUCP', 'STACK_CUUP', 'DU_OAM'])
            current_time: Current time string (format: 'YYYY-MM-DD HH:MM:SS')
            output_dir: Output directory for archive
            
        Returns:
            Dictionary with collection results
        """
        try:
            logger.info(f"Starting log collection for software: {software_list}")
            
            # Reset collection state
            self.collected_logs = []
            self._cleanup_temp_directory()
            
            # Collect logs for each software component
            for component in software_list:
                if component not in self.SOFTWARE_COMPONENTS:
                    logger.warning(f"Unknown software component: {component}")
                    continue
                
                logger.info(f"Collecting logs for software component: {component}")
                
                comp_info = self.SOFTWARE_COMPONENTS[component]
                
                if comp_info['location'] == 'local':
                    self._collect_local_logs(comp_info['log_path'], component, current_time)
                else:
                    self._collect_remote_logs(comp_info['ip'], comp_info['log_path'], component, current_time)
            
            # Create archive
            archive_path = self._create_archive(current_time, output_dir)
            
            # Prepare result
            result = {
                'status': 'success' if archive_path else 'partial_success',
                'archive_path': archive_path,
                'collected_logs': self.collected_logs,
                'total_components': len(self.collected_logs),
                'timestamp': current_time
            }
            
            if not archive_path:
                result['status'] = 'error'
                result['message'] = 'Failed to create archive'
            
            return result
            
        except Exception as e:
            logger.error(f"Error in collect_logs_by_software: {str(e)}")
            return {
                'status': 'error',
                'message': str(e),
                'collected_logs': self.collected_logs,
                'timestamp': current_time
            }
        finally:
            self._cleanup_temp_directory()
    
    def collect_all_logs(self, current_time: str, output_dir: str = '/opt/soft/Satellite_McpServer/ftp_data/logs') -> Dict:
        """
        Collect all available logs
        
        Args:
            current_time: Current time string (format: 'YYYY-MM-DD HH:MM:SS')
            output_dir: Output directory for archive
            
        Returns:
            Dictionary with collection results
        """
        all_software = list(self.SOFTWARE_COMPONENTS.keys())
        return self.collect_logs_by_software(all_software, current_time, output_dir)
    
    def get_available_components(self) -> Dict:
        """
        Get information about available hardware and software components
        
        Returns:
            Dictionary with available components information
        """
        return {
            'hardware_boards': list(self.HARDWARE_MAPPING.keys()),
            'software_components': list(self.SOFTWARE_COMPONENTS.keys()),
            'hardware_to_software_mapping': self.HARDWARE_TO_SOFTWARE,
            'software_details': self.SOFTWARE_COMPONENTS
        }


# Convenience functions for MCP integration
def collect_logs_by_hardware(hardware_list: List[str], current_time: str, 
                           sftp_username: str = 'root', sftp_password: str = 'root',
                           output_dir: str = '/opt/soft/Satellite_McpServer/ftp_data/logs') -> Dict:
    """
    Collect logs by hardware board (convenience function for MCP)
    
    Args:
        hardware_list: List of hardware board names
        current_time: Current time string (format: 'YYYY-MM-DD HH:MM:SS')
        sftp_username: SFTP username
        sftp_password: SFTP password
        output_dir: Output directory for archive
        
    Returns:
        Dictionary with collection results
    """
    collector = LogCollector(sftp_username, sftp_password)
    return collector.collect_logs_by_hardware(hardware_list, current_time, output_dir)


def collect_logs_by_software(software_list: List[str], current_time: str,
                           sftp_username: str = 'root', sftp_password: str = 'root',
                           output_dir: str = '/opt/soft/Satellite_McpServer/ftp_data/logs') -> Dict:
    """
    Collect logs by software component (convenience function for MCP)
    
    Args:
        software_list: List of software component names
        current_time: Current time string (format: 'YYYY-MM-DD HH:MM:SS')
        sftp_username: SFTP username
        sftp_password: SFTP password
        output_dir: Output directory for archive
        
    Returns:
        Dictionary with collection results
    """
    collector = LogCollector(sftp_username, sftp_password)
    return collector.collect_logs_by_software(software_list, current_time, output_dir)


def collect_all_logs(current_time: str,
                    sftp_username: str = 'root', sftp_password: str = 'root',
                    output_dir: str = '/opt/soft/Satellite_McpServer/ftp_data/logs') -> Dict:
    """
    Collect all available logs (convenience function for MCP)
    
    Args:
        current_time: Current time string (format: 'YYYY-MM-DD HH:MM:SS')
        sftp_username: SFTP username
        sftp_password: SFTP password
        output_dir: Output directory for archive
        
    Returns:
        Dictionary with collection results
    """
    collector = LogCollector(sftp_username, sftp_password)
    return collector.collect_all_logs(current_time, output_dir)


def get_available_components() -> Dict:
    """
    Get information about available hardware and software components
    
    Returns:
        Dictionary with available components information
    """
    collector = LogCollector()
    return collector.get_available_components()


if __name__ == '__main__':
    # Example usage
    import argparse
    
    parser = argparse.ArgumentParser(description='Collect logs from satellite base station system')
    parser.add_argument('--hardware', nargs='+', help='Hardware boards to collect logs from')
    parser.add_argument('--software', nargs='+', help='Software components to collect logs from')
    parser.add_argument('--all', action='store_true', help='Collect all available logs')
    parser.add_argument('--current-time', required=True, help='Current time (YYYY-MM-DD HH:MM:SS)')
    parser.add_argument('--output-dir', default='/opt/soft/Satellite_McpServer/ftp_data/logs', help='Output directory')
    parser.add_argument('--sftp-username', default='root', help='SFTP username')
    parser.add_argument('--sftp-password', default='root', help='SFTP password')
    parser.add_argument('--list-components', action='store_true', help='List available components')
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    if args.list_components:
        components = get_available_components()
        print(json.dumps(components, indent=2))
        sys.exit(0)
    
    if args.all:
        result = collect_all_logs(args.current_time, args.sftp_username, args.sftp_password, args.output_dir)
    elif args.hardware:
        result = collect_logs_by_hardware(args.hardware, args.current_time, args.sftp_username, args.sftp_password, args.output_dir)
    elif args.software:
        result = collect_logs_by_software(args.software, args.current_time, args.sftp_username, args.sftp_password, args.output_dir)
    else:
        parser.print_help()
        sys.exit(1)
    
    print(json.dumps(result, indent=2))