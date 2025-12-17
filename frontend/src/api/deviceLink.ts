import type { DeviceInfo, DeviceListResponse } from '@/types'
import api from './index'

export const deviceLinkApi = {
  /**
   * 获取设备列表
   */
  listDevices: () => api.get<DeviceListResponse>('/api/v1/device-links'),

  /**
   * 手动ping某个设备，强制刷新状态
   */
  pingDevice: (deviceId: string) =>
    api.get<DeviceInfo>(`/api/v1/device-links/${encodeURIComponent(deviceId)}/ping`),

  /**
   * 删除设备记录
   */
  deleteDevice: (deviceId: string) =>
    api.delete<DeviceInfo>(`/api/v1/device-links/${encodeURIComponent(deviceId)}`),
}

export default deviceLinkApi
