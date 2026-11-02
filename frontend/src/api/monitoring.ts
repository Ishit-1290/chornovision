import { request } from './client';
import type { MonitoringCommandResponse, MonitoringStatus } from './types';

export function getMonitoringStatus(): Promise<MonitoringStatus> {
  return request<MonitoringStatus>('/api/monitoring/status');
}

export function startMonitoring(): Promise<MonitoringCommandResponse> {
  return request<MonitoringCommandResponse>('/api/monitoring/start', { method: 'POST' });
}

export function pauseMonitoring(): Promise<MonitoringCommandResponse> {
  return request<MonitoringCommandResponse>('/api/monitoring/pause', { method: 'POST' });
}

export function stopMonitoring(): Promise<MonitoringCommandResponse> {
  return request<MonitoringCommandResponse>('/api/monitoring/stop', { method: 'POST' });
}
