import { useMemo, useState } from 'react';
import type { Lead, Tier } from '../types';
import { Icon } from './Icons';
import { ScoreChip, fmtTime } from './atoms';

type Filter = 'ALL' | Tier;

interface FilterChipProps {
  label: string;
  count: number;
  active: boolean;
  dot?: string;
  onClick: () => void;
}

function FilterChip({ label, count, active, dot, onClick }: FilterChipProps) {
  return (
    <button
      onClick={onClick}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: '5px 11px',
        borderRadius: 999,
        border: active ? 'none' : '1px solid var(--border)',
        background: active ? 'var(--ink)' : 'transparent',
        color: active ? 'var(--surface)' : 'var(--ink-muted)',
        fontSize: 12,
        fontWeight: 500,
        transition: 'all 150ms ease',
      }}
    >
      {dot && (
        <span
          style={{
            width: 5,
            height: 5,
            borderRadius: 999,
            background: dot,
          }}
        />
      )}
      {label}
      <span
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          opacity: active ? 0.85 : 0.7,
        }}
      >
        {count}
      </span>
    </button>
  );
}

interface QueueRowProps {
  lead: Lead;
  selected: boolean;
  onClick: () => void;
}

function QueueRow({ lead, selected, onClick }: QueueRowProps) {
  const tierFg = `var(--${lead.score.tier.toLowerCase()}-fg)`;
  return (
    <div
      onClick={onClick}
      style={{
        padding: '11px 20px',
        cursor: 'pointer',
        background: selected ? 'var(--selected)' : 'transparent',
        borderLeft: selected ? `2px solid ${tierFg}` : '2px solid transparent',
        transition: 'background 100ms ease',
      }}
      onMouseEnter={(e) => {
        if (!selected) (e.currentTarget as HTMLElement).style.background = 'var(--hover)';
      }}
      onMouseLeave={(e) => {
        if (!selected) (e.currentTarget as HTMLElement).style.background = 'transparent';
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
          <span
            style={{
              fontSize: 13.5,
              fontWeight: 500,
              color: 'var(--ink)',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {lead.restaurant_name}
          </span>
          {lead.sdr_state.contacted_today && (
            <span
              style={{
                width: 5,
                height: 5,
                borderRadius: 999,
                background: 'var(--accent)',
                flexShrink: 0,
              }}
            />
          )}
        </div>
        <ScoreChip score={lead.score.numeric_score} tier={lead.score.tier} />
      </div>
      <div
        style={{
          fontSize: 11.5,
          color: 'var(--ink-muted)',
          marginTop: 2,
          display: 'flex',
          justifyContent: 'space-between',
          gap: 8,
        }}
      >
        <span
          style={{
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}
        >
          {[lead.city && `${lead.city}, ${lead.state ?? ''}`, lead.cuisine_type, lead.sdr_state.dialed_today && 'called']
            .filter(Boolean)
            .join(' · ')}
        </span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, flexShrink: 0 }}>
          {fmtTime(lead.call.started_at)}
        </span>
      </div>
      {lead.one_liner && (
        <div
          style={{
            fontSize: 12,
            color: 'var(--ink-muted)',
            marginTop: 6,
            display: '-webkit-box',
            WebkitLineClamp: 2,
            WebkitBoxOrient: 'vertical',
            overflow: 'hidden',
          }}
        >
          {lead.one_liner}
        </div>
      )}
    </div>
  );
}

interface QueuePaneProps {
  leads: Lead[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}

export function QueuePane({ leads, selectedId, onSelect }: QueuePaneProps) {
  const [filter, setFilter] = useState<Filter>('ALL');
  const [query, setQuery] = useState('');

  const counts = useMemo(() => {
    const out: Record<Filter, number> = { ALL: leads.length, HOT: 0, WARM: 0, COLD: 0 };
    for (const lead of leads) out[lead.score.tier]++;
    return out;
  }, [leads]);

  const filtered = useMemo(() => {
    let out = filter === 'ALL' ? leads : leads.filter((l) => l.score.tier === filter);
    if (query) {
      const q = query.toLowerCase();
      out = out.filter(
        (l) =>
          l.restaurant_name.toLowerCase().includes(q) ||
          (l.city ?? '').toLowerCase().includes(q) ||
          (l.cuisine_type ?? '').toLowerCase().includes(q),
      );
    }
    return out;
  }, [leads, filter, query]);

  const grouped = useMemo(() => {
    const out: Record<Tier, Lead[]> = { HOT: [], WARM: [], COLD: [] };
    for (const lead of filtered) out[lead.score.tier].push(lead);
    return out;
  }, [filtered]);

  return (
    <aside
      style={{
        width: 360,
        background: 'var(--surface)',
        borderRight: '1px solid var(--border)',
        display: 'flex',
        flexDirection: 'column',
        flexShrink: 0,
      }}
    >
      <div style={{ padding: '20px 20px 12px', borderBottom: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
          <h2 style={{ margin: 0, fontSize: 17, fontWeight: 600 }}>Today's Queue</h2>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--ink-muted)' }}>
            {filtered.length}/{leads.length}
          </span>
        </div>

        <div
          style={{
            marginTop: 12,
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '7px 10px',
            borderRadius: 8,
            background: 'var(--surface-2)',
          }}
        >
          <span style={{ color: 'var(--ink-muted)', display: 'flex' }}>
            <Icon.Search s={14} />
          </span>
          <input
            type="text"
            placeholder="Search restaurants, cities…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            style={{
              flex: 1,
              border: 'none',
              background: 'transparent',
              outline: 'none',
              fontSize: 13,
              fontFamily: 'inherit',
              color: 'var(--ink)',
            }}
          />
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 10,
              color: 'var(--ink-faint)',
              padding: '2px 5px',
              borderRadius: 4,
              border: '1px solid var(--border)',
            }}
          >
            ⌘K
          </span>
        </div>

        <div style={{ display: 'flex', gap: 6, marginTop: 10, flexWrap: 'wrap' }}>
          <FilterChip
            label="All"
            count={counts.ALL}
            active={filter === 'ALL'}
            onClick={() => setFilter('ALL')}
          />
          <FilterChip
            label="Hot"
            count={counts.HOT}
            active={filter === 'HOT'}
            dot="var(--hot-fg)"
            onClick={() => setFilter('HOT')}
          />
          <FilterChip
            label="Warm"
            count={counts.WARM}
            active={filter === 'WARM'}
            dot="var(--warm-fg)"
            onClick={() => setFilter('WARM')}
          />
          <FilterChip
            label="Cold"
            count={counts.COLD}
            active={filter === 'COLD'}
            dot="var(--cold-fg)"
            onClick={() => setFilter('COLD')}
          />
        </div>
      </div>

      <div style={{ overflowY: 'auto', flex: 1 }}>
        {(['HOT', 'WARM', 'COLD'] as Tier[]).map((tier) => {
          const items = grouped[tier];
          if (items.length === 0) return null;
          return (
            <section key={tier}>
              <header
                style={{
                  padding: '12px 20px 6px',
                  fontSize: 10,
                  fontWeight: 600,
                  letterSpacing: '0.12em',
                  textTransform: 'uppercase',
                  fontFamily: 'var(--font-mono)',
                  color: 'var(--ink-muted)',
                  background: 'var(--surface)',
                  position: 'sticky',
                  top: 0,
                  zIndex: 1,
                }}
              >
                {tier} · {items.length}
              </header>
              {items.map((lead) => (
                <QueueRow
                  key={lead.id}
                  lead={lead}
                  selected={lead.id === selectedId}
                  onClick={() => onSelect(lead.id)}
                />
              ))}
            </section>
          );
        })}
        {filtered.length === 0 && (
          <div
            style={{
              padding: 40,
              textAlign: 'center',
              color: 'var(--ink-faint)',
              fontSize: 13,
            }}
          >
            No leads match.
          </div>
        )}
      </div>
    </aside>
  );
}
