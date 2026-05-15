import type { ReactNode } from 'react';
import { Icon } from './Icons';

interface RailItemProps {
  icon: ReactNode;
  label: string;
  badge?: number;
  active?: boolean;
}

function RailItem({ icon, label, badge, active }: RailItemProps) {
  return (
    <button
      title={label}
      style={{
        position: 'relative',
        width: 40,
        height: 40,
        borderRadius: 8,
        border: 'none',
        background: active ? 'var(--surface-2)' : 'transparent',
        color: active ? 'var(--ink)' : 'var(--ink-muted)',
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        transition: 'background 150ms ease',
      }}
    >
      {active && (
        <span
          style={{
            position: 'absolute',
            left: -6,
            top: 10,
            width: 2,
            height: 20,
            background: 'var(--accent)',
            borderRadius: 1,
          }}
        />
      )}
      {icon}
      {badge != null && badge > 0 && (
        <span
          style={{
            position: 'absolute',
            top: 4,
            right: 4,
            minWidth: 16,
            height: 16,
            padding: '0 4px',
            borderRadius: 999,
            background: 'var(--accent)',
            color: 'var(--surface)',
            fontFamily: 'var(--font-mono)',
            fontSize: 9,
            fontWeight: 600,
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          {badge}
        </span>
      )}
    </button>
  );
}

export function NavRail({ queueCount }: { queueCount: number }) {
  return (
    <nav
      style={{
        width: 60,
        background: 'var(--surface)',
        borderRight: '1px solid var(--border)',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        padding: '14px 0',
        gap: 6,
        flexShrink: 0,
      }}
    >
      <RailItem icon={<Icon.Inbox />} label="Queue" badge={queueCount} active />
      <RailItem icon={<Icon.Calls />} label="Calls" />
      <RailItem icon={<Icon.Library />} label="Library" />
      <RailItem icon={<Icon.Insights />} label="Insights" />
      <div style={{ flex: 1 }} />
      <RailItem icon={<Icon.Settings />} label="Settings" />
    </nav>
  );
}
