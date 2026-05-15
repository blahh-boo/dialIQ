import { useEffect, useState } from 'react';
import { useLeads } from './api';
import { DetailPane } from './components/DetailPane';
import { NavRail } from './components/NavRail';
import { QueuePane } from './components/QueuePane';
import { TopBar } from './components/TopBar';

export function App() {
  const { data, isLoading, error } = useLeads();
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const leads = data?.leads ?? [];

  useEffect(() => {
    if (selectedId == null && leads.length > 0) {
      setSelectedId(leads[0].id);
    }
  }, [selectedId, leads]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <TopBar />
      <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
        <NavRail queueCount={leads.length} />
        {isLoading ? (
          <div style={{ flex: 1, padding: 40, color: 'var(--ink-faint)' }}>Loading queue…</div>
        ) : error ? (
          <div style={{ flex: 1, padding: 40, color: 'var(--hot-fg)' }}>
            Failed to load queue. Is the backend running on :8000?
          </div>
        ) : (
          <>
            <QueuePane leads={leads} selectedId={selectedId} onSelect={setSelectedId} />
            <DetailPane leadId={selectedId} />
          </>
        )}
      </div>
    </div>
  );
}
