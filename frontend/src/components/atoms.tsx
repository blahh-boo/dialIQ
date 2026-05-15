import type { Tier } from '../types';

export function MapleMark({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="10" fill="var(--accent)" />
      <circle cx="12" cy="12" r="4" fill="var(--cream)" />
    </svg>
  );
}

const TIER_COLORS: Record<Tier, { bg: string; fg: string }> = {
  HOT: { bg: 'var(--hot-bg)', fg: 'var(--hot-fg)' },
  WARM: { bg: 'var(--warm-bg)', fg: 'var(--warm-fg)' },
  COLD: { bg: 'var(--cold-bg)', fg: 'var(--cold-fg)' },
};

export function TierPill({ tier, size = 'sm' }: { tier: Tier; size?: 'sm' | 'lg' }) {
  const c = TIER_COLORS[tier];
  const px = size === 'lg' ? '6px 12px' : '3px 8px';
  const fs = size === 'lg' ? 12 : 10.5;
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: px,
        borderRadius: 999,
        background: c.bg,
        color: c.fg,
        fontSize: fs,
        fontWeight: 600,
        letterSpacing: '0.06em',
        fontFamily: 'var(--font-mono)',
        textTransform: 'uppercase',
      }}
    >
      <span
        style={{
          width: 5,
          height: 5,
          borderRadius: 999,
          background: c.fg,
          boxShadow: `0 0 0 3px ${c.bg}`,
        }}
      />
      {tier}
    </span>
  );
}

export function ScoreBar({ score, tier }: { score: number; tier: Tier }) {
  const tierColor = `var(--${tier.toLowerCase()}-fg)`;
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 16 }}>
      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 48,
          fontWeight: 500,
          letterSpacing: '-0.04em',
          color: 'var(--ink)',
          lineHeight: 1,
        }}
      >
        {score}
        <span style={{ fontSize: 18, color: 'var(--ink-muted)' }}>/100</span>
      </div>
      <div
        style={{
          flex: 1,
          height: 6,
          background: 'var(--surface-2)',
          borderRadius: 999,
          position: 'relative',
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            position: 'absolute',
            inset: 0,
            width: `${score}%`,
            background: tierColor,
            borderRadius: 999,
            transition: 'width 400ms cubic-bezier(.2,.7,.2,1)',
          }}
        />
      </div>
    </div>
  );
}

export function ScoreChip({ score, tier }: { score: number; tier: Tier }) {
  const tierColor = `var(--${tier.toLowerCase()}-fg)`;
  return (
    <div
      style={{
        fontFamily: 'var(--font-mono)',
        fontSize: 13,
        fontWeight: 500,
        color: tierColor,
        minWidth: 28,
        textAlign: 'right',
        letterSpacing: '-0.02em',
      }}
    >
      {score}
    </div>
  );
}

export function KV({ label, value, mono = false }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'baseline',
        gap: 12,
        padding: '8px 0',
        borderBottom: '1px dashed var(--border)',
      }}
    >
      <span style={{ fontSize: 12, color: 'var(--ink-muted)', letterSpacing: '0.02em' }}>{label}</span>
      <span
        style={{
          fontSize: 13,
          color: 'var(--ink)',
          fontFamily: mono ? 'var(--font-mono)' : 'inherit',
          textAlign: 'right',
        }}
      >
        {value}
      </span>
    </div>
  );
}

export function fmtDuration(s: number | null | undefined): string {
  if (s == null || s === 0) return '—';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return m > 0 ? `${m}m${String(sec).padStart(2, '0')}s` : `${sec}s`;
}

export function fmtTime(iso: string | null): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
    });
  } catch {
    return '—';
  }
}
