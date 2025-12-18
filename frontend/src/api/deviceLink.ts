import type { DeviceInfo, DeviceListResponse } from '@/types'
import api from './index'

export const deviceLinkApi = {
  /**
   * 获取设备列表
   */
  listDevices: () => api.get<DeviceListResponse>('/api/v1/device-links'),
  /**
   * 获取单个设备详情（当前后端未提供专门接口，这里通过列表筛选）
   */
  getDevice: async (deviceId: string): Promise<DeviceInfo | null> => {
    const res = await api.get<DeviceListResponse>('/api/v1/device-links')
    return res.devices?.find((item) => item.id === deviceId) || null
  },

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
