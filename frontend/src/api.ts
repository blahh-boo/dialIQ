import { useQuery } from '@tanstack/react-query';
import type { CampaignStats, Lead, LeadDetail, Me } from './types';

const BASE = '/api';

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'X-SDR-Id': '1' },
  });
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText}`);
  }
  return res.json();
}

export function useLeads() {
  return useQuery({
    queryKey: ['leads'],
    queryFn: () => get<{ leads: Lead[] }>('/leads'),
  });
}

export function useLead(id: number | null) {
  return useQuery({
    queryKey: ['lead', id],
    queryFn: () => get<LeadDetail>(`/leads/${id}`),
    enabled: id != null,
  });
}

export function useMe() {
  return useQuery({
    queryKey: ['me'],
    queryFn: () => get<Me>('/me'),
  });
}

export function useCampaignStats() {
  return useQuery({
    queryKey: ['campaign-stats'],
    queryFn: () => get<CampaignStats>('/campaign/stats'),
    staleTime: 30_000,
  });
}
