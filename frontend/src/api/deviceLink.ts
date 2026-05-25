import type { DeviceInfo, DeviceListResponse } from '@/types'
import api from './index'

export const deviceLinkApi = {
  /**
   * 获取设备列表
   */
  listDevices: (): Promise<DeviceListResponse> =>
    api.get('/api/v1/device-links') as unknown as Promise<DeviceListResponse>,
  /**
   * 获取单个设备详情（当前后端未提供专门接口，这里通过列表筛选）
   */
  getDevice: async (deviceId: string): Promise<DeviceInfo | null> => {
    const res = await deviceLinkApi.listDevices()
    return res.devices?.find((item: DeviceInfo) => item.id === deviceId) || null
  },

  /**
   * 手动ping某个设备，强制刷新状态
   */
  pingDevice: (deviceId: string) =>
    api.get(`/api/v1/device-links/${encodeURIComponent(deviceId)}/ping`) as unknown as Promise<DeviceInfo>,

  /**
   * 删除设备记录
   */
  deleteDevice: (deviceId: string) =>
    api.delete(`/api/v1/device-links/${encodeURIComponent(deviceId)}`) as unknown as Promise<DeviceInfo>,
}

export default deviceLinkApi
