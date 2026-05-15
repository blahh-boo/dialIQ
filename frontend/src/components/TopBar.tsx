import { useCampaignStats, useMe } from '../api';
import { Icon } from './Icons';
import { MapleMark } from './atoms';

function CampaignChip({
  dot,
  label,
  detail,
}: {
  dot?: string;
  label: string;
  detail: string;
}) {
  return (
    <div
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 8,
        padding: '6px 12px',
        borderRadius: 999,
        background: 'var(--surface-2)',
        fontSize: 12,
      }}
    >
      {dot && (
        <span
          style={{
            width: 6,
            height: 6,
            borderRadius: 999,
            background: dot,
          }}
        />
      )}
      <span style={{ color: 'var(--ink)', fontWeight: 500 }}>{label}</span>
      <span style={{ color: 'var(--ink-muted)' }}>· {detail}</span>
    </div>
  );
}

export function TopBar() {
  const { data: me } = useMe();
  const { data: stats } = useCampaignStats();

  return (
    <header
      style={{
        height: 56,
        background: 'var(--surface)',
        borderBottom: '1px solid var(--border)',
        display: 'flex',
        alignItems: 'center',
        padding: '0 20px',
        gap: 24,
        flexShrink: 0,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 188 }}>
        <MapleMark />
        <span style={{ fontSize: 16, fontWeight: 600, letterSpacing: '-0.01em' }}>Maple</span>
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            fontWeight: 500,
            padding: '2px 8px',
            borderRadius: 999,
            background: 'var(--surface-2)',
            color: 'var(--ink-muted)',
          }}
        >
          SDR
        </span>
      </div>

      <div style={{ display: 'flex', gap: 8, flex: 1, flexWrap: 'wrap' }}>
        {stats && (
          <>
            <CampaignChip
              dot="var(--accent)"
              label={`${stats.campaign_name} · ${stats.total_leads.toLocaleString()} leads`}
              detail="Campaign"
            />
            <CampaignChip
              label={`${stats.mystery_shopped} mystery-shopped`}
              detail={`Avg ${stats.avg_score}/100`}
            />
            <CampaignChip
              dot="var(--hot-fg)"
              label={`${stats.hot_count} HOT`}
              detail={`${stats.no_pickup_count} no-pickup`}
            />
            <CampaignChip
              dot={stats.touched_today > 0 ? 'var(--cold-fg)' : 'var(--ink-faint)'}
              label={`${stats.touched_today} touched today`}
              detail="By you"
            />
          </>
        )}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <button
          style={{
            width: 32,
            height: 32,
            borderRadius: 8,
            border: '1px solid var(--border)',
            background: 'var(--surface)',
            color: 'var(--ink-muted)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
          aria-label="AI"
        >
          <Icon.Sparkle s={14} />
        </button>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '3px 10px 3px 3px',
            borderRadius: 999,
            background: 'var(--surface-2)',
          }}
        >
          <span
            style={{
              width: 26,
              height: 26,
              borderRadius: '50%',
              background: 'var(--accent)',
              color: 'var(--surface)',
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 11,
              fontWeight: 600,
            }}
          >
            {me?.initials ?? '··'}
          </span>
          <span style={{ fontSize: 13 }}>{me?.name ?? 'Loading…'}</span>
        </div>
      </div>
    </header>
  );
}
