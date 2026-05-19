import { useState } from 'react';
import { useLead } from '../api';
import type { CallFacts, Lead, TranscriptTurn } from '../types';
import { Icon } from './Icons';
import { KV, ScoreBar, TierPill, fmtDuration, fmtTime } from './atoms';

export function DetailPane({ leadId }: { leadId: number | null }) {
  if (leadId == null) {
    return (
      <main
        style={{
          flex: 1,
          background: 'var(--cream)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: 'var(--ink-faint)',
          fontSize: 14,
        }}
      >
        Select a lead from the queue.
      </main>
    );
  }
  return <DetailPaneInner leadId={leadId} />;
}

function DetailPaneInner({ leadId }: { leadId: number }) {
  const { data, isLoading, error } = useLead(leadId);

  if (isLoading) {
    return (
      <main style={paneStyle}>
        <div style={{ color: 'var(--ink-faint)', padding: 40 }}>Loading…</div>
      </main>
    );
  }
  if (error || !data) {
    return (
      <main style={paneStyle}>
        <div style={{ color: 'var(--hot-fg)', padding: 40 }}>Failed to load lead.</div>
      </main>
    );
  }

  const { lead, transcript } = data;

  return (
    <main style={paneStyle}>
      <div style={{ maxWidth: 880, padding: '28px 40px' }}>
        <Hero lead={lead} />
        <CallRecording lead={lead} transcript={transcript} />
        <ScoreBreakdown lead={lead} />
        <LeadDetails lead={lead} />
      </div>
    </main>
  );
}

const paneStyle: React.CSSProperties = {
  flex: 1,
  background: 'var(--cream)',
  overflowY: 'auto',
};

function Hero({ lead }: { lead: Lead }) {
  const subLine = [
    lead.city && `${lead.city}${lead.state ? `, ${lead.state}` : ''}`,
    lead.cuisine_type,
    lead.google_reviews_count != null && `★ ${lead.google_reviews_count.toLocaleString()} reviews`,
    lead.website && `🌐 ${lead.website}`,
  ]
    .filter(Boolean)
    .join(' · ');

  const callLine = lead.score.pickup
    ? `Called ${fmtTime(lead.call.started_at)} · ${fmtDuration(lead.call.duration_seconds)} call`
    : `Called ${fmtTime(lead.call.started_at)} · ${describeAnsweredBy(lead.answered_by)}`;

  return (
    <section style={{ marginBottom: 28 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
        <TierPill tier={lead.score.tier} size="lg" />
        <span style={{ fontSize: 12, color: 'var(--ink-muted)' }}>{callLine}</span>
      </div>
      <h1
        style={{
          fontSize: 30,
          fontWeight: 500,
          letterSpacing: '-0.022em',
          margin: '0 0 8px',
        }}
      >
        {lead.restaurant_name}
      </h1>
      <div style={{ fontSize: 13.5, color: 'var(--ink-muted)', marginBottom: 24 }}>{subLine}</div>
      <ScoreBar score={lead.score.numeric_score} tier={lead.score.tier} />
      <SDRBrief lead={lead} />
    </section>
  );
}

function SDRBrief({ lead }: { lead: Lead }) {
  if (!lead.one_liner) return null;
  const tierFg = `var(--${lead.score.tier.toLowerCase()}-fg)`;
  return (
    <div
      style={{
        marginTop: 28,
        position: 'relative',
        background: 'var(--cream)',
        border: '1px solid var(--border)',
        borderRadius: 10,
        padding: '22px 22px 18px',
      }}
    >
      <span
        style={{
          position: 'absolute',
          top: -8,
          left: 16,
          padding: '2px 8px',
          background: 'var(--surface)',
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          fontWeight: 600,
          letterSpacing: '0.08em',
          color: 'var(--ink-muted)',
          textTransform: 'uppercase',
        }}
      >
        ✦ SDR BRIEF
      </span>
      <p
        style={{
          margin: 0,
          fontFamily: 'var(--font-serif)',
          fontSize: 22,
          lineHeight: 1.35,
          color: 'var(--ink)',
        }}
      >
        {lead.one_liner}
      </p>
      {lead.key_failure_quote && (
        <blockquote
          style={{
            margin: '14px 0 0',
            paddingLeft: 12,
            borderLeft: `2px solid ${tierFg}`,
            fontSize: 13,
            fontStyle: 'italic',
            color: 'var(--ink-muted)',
          }}
        >
          {lead.key_failure_quote}
        </blockquote>
      )}
    </div>
  );
}

function CallRecording({ lead, transcript }: { lead: Lead; transcript: TranscriptTurn[] }) {
  return (
    <section style={{ marginBottom: 28 }}>
      <header
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          fontWeight: 600,
          letterSpacing: '0.12em',
          textTransform: 'uppercase',
          color: 'var(--ink-muted)',
          marginBottom: 10,
          display: 'flex',
          justifyContent: 'space-between',
        }}
      >
        <span>CALL RECORDING</span>
        <span>
          {fmtDuration(lead.call.duration_seconds)} · {lead.answered_by}
        </span>
      </header>

      {!lead.score.pickup ? (
        <NoPickupCard lead={lead} />
      ) : (
        <>
          <PlaybackCard duration={lead.call.duration_seconds ?? 0} />
          {transcript.length > 0 && <TranscriptView transcript={transcript} />}
        </>
      )}
    </section>
  );
}

function PlaybackCard({ duration }: { duration: number }) {
  const [playing, setPlaying] = useState(false);
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 16,
        padding: '14px 16px',
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: 10,
      }}
    >
      <button
        onClick={() => setPlaying((p) => !p)}
        style={{
          width: 36,
          height: 36,
          borderRadius: '50%',
          border: 'none',
          background: 'var(--ink)',
          color: 'var(--surface)',
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
        aria-label={playing ? 'Pause' : 'Play'}
      >
        {playing ? <Icon.Pause s={14} /> : <Icon.Play s={14} />}
      </button>
      <div
        style={{
          flex: 1,
          height: 36,
          display: 'flex',
          alignItems: 'center',
          gap: 2,
        }}
      >
        {Array.from({ length: 60 }).map((_, i) => {
          const v = 0.3 + Math.abs(Math.sin(i * 1.2)) * 0.7;
          return (
            <div
              key={i}
              style={{
                flex: 1,
                height: `${v * 100}%`,
                minWidth: 2,
                background: 'var(--ink-faint)',
                opacity: 0.5,
                borderRadius: 1,
              }}
            />
          );
        })}
      </div>
      <span
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 12,
          color: 'var(--ink-muted)',
          minWidth: 40,
          textAlign: 'right',
        }}
      >
        {fmtDuration(duration)}
      </span>
    </div>
  );
}

function TranscriptView({ transcript }: { transcript: TranscriptTurn[] }) {
  return (
    <div
      style={{
        marginTop: 12,
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: 10,
        padding: '10px 16px',
        maxHeight: 'min(600px, 55vh)',
        overflowY: 'auto',
      }}
    >
      {transcript.map((turn, i) => (
        <div
          key={i}
          style={{
            display: 'grid',
            gridTemplateColumns: '50px 80px 1fr',
            gap: 12,
            padding: '8px 0',
            fontSize: 13,
          }}
        >
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ink-muted)' }}>
            {formatTimestamp(turn.t)}
          </span>
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 10,
              fontWeight: 600,
              letterSpacing: '0.08em',
              textTransform: 'uppercase',
              color: roleColor(turn.role),
              fontStyle: turn.role === 'system' ? 'italic' : 'normal',
            }}
          >
            {turn.role === 'shopper' ? 'Maple AI' : turn.role === 'restaurant' ? 'Restaurant' : 'System'}
          </span>
          <span style={{ color: turn.role === 'system' ? 'var(--ink-faint)' : 'var(--ink)' }}>{turn.text}</span>
        </div>
      ))}
    </div>
  );
}

function roleColor(role: TranscriptTurn['role']): string {
  if (role === 'shopper') return 'var(--accent)';
  if (role === 'restaurant') return 'var(--ink-muted)';
  return 'var(--ink-faint)';
}

function formatTimestamp(t: number): string {
  const m = Math.floor(t / 60);
  const s = t % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

function NoPickupCard({ lead }: { lead: Lead }) {
  const label = describeAnsweredBy(lead.answered_by);
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 14,
        padding: '16px 18px',
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: 10,
      }}
    >
      <div
        style={{
          width: 36,
          height: 36,
          borderRadius: '50%',
          background: 'var(--hot-bg)',
          color: 'var(--hot-fg)',
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Icon.Phone s={16} />
      </div>
      <div>
        <div style={{ fontWeight: 500, fontSize: 14 }}>{label}</div>
        <div style={{ fontSize: 12.5, color: 'var(--ink-muted)', marginTop: 2 }}>
          The mystery shopper couldn't get through — that's the headline. Use it.
        </div>
      </div>
    </div>
  );
}

function describeAnsweredBy(a: Lead['answered_by']): string {
  switch (a) {
    case 'VOICEMAIL':
      return 'Went to voicemail';
    case 'IVR':
      return 'Stuck in IVR';
    case 'BUSY':
      return 'Line busy';
    case 'NO_ANSWER':
      return 'No answer';
    default:
      return 'Answered';
  }
}

function ScoreBreakdown({ lead }: { lead: Lead }) {
  const [showAll, setShowAll] = useState(false);
  const totalDeducted = lead.score.deductions.reduce((sum, d) => sum + d.points, 0);
  const visible = showAll ? lead.score.deductions : lead.score.deductions.slice(0, 4);
  const tierFg = `var(--${lead.score.tier.toLowerCase()}-fg)`;

  return (
    <section style={{ marginBottom: 28 }}>
      <header
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          fontWeight: 600,
          letterSpacing: '0.12em',
          textTransform: 'uppercase',
          color: 'var(--ink-muted)',
          marginBottom: 10,
        }}
      >
        SCORE BREAKDOWN
      </header>

      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          fontFamily: 'var(--font-mono)',
          fontSize: 12,
          color: 'var(--ink-muted)',
          marginBottom: 6,
        }}
      >
        <span>Starting 100 → {lead.score.numeric_score}</span>
        <span style={{ color: tierFg }}>−{totalDeducted} pts</span>
      </div>

      <DeductionStack deductions={lead.score.deductions} />

      <div style={{ marginTop: 14 }}>
        {visible.map((d, i) => (
          <div
            key={i}
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'baseline',
              padding: '8px 0',
              borderBottom: '1px dashed var(--border)',
              fontSize: 13,
            }}
          >
            <span style={{ color: 'var(--ink)' }}>{d.reason}</span>
            <span style={{ fontFamily: 'var(--font-mono)', color: tierFg }}>−{d.points}</span>
          </div>
        ))}
        {lead.score.deductions.length > 4 && (
          <button
            onClick={() => setShowAll((s) => !s)}
            style={{
              marginTop: 8,
              border: 'none',
              background: 'transparent',
              color: 'var(--ink-muted)',
              fontSize: 12,
            }}
          >
            {showAll ? 'Show less' : `Show ${lead.score.deductions.length - 4} more`}
          </button>
        )}
      </div>

      <CallFactsGrid facts={lead.facts} />
    </section>
  );
}

function DeductionStack({ deductions }: { deductions: Lead['score']['deductions'] }) {
  if (deductions.length === 0) return null;
  const total = deductions.reduce((sum, d) => sum + d.points, 0);
  return (
    <div
      style={{
        display: 'flex',
        height: 6,
        borderRadius: 999,
        overflow: 'hidden',
        background: 'var(--surface-2)',
      }}
    >
      {deductions.map((d, i) => (
        <div
          key={i}
          title={`${d.reason}: -${d.points}`}
          style={{
            width: `${(d.points / Math.max(total, 100)) * 100}%`,
            background: i % 2 === 0 ? 'var(--ink-muted)' : 'var(--ink-faint)',
          }}
        />
      ))}
    </div>
  );
}

function CallFactsGrid({ facts }: { facts: CallFacts }) {
  const cells: Array<[string, React.ReactNode, boolean]> = [
    ['Pickup', facts.pickup ? 'Yes' : 'No', !facts.pickup],
    ['Rings', facts.rings_to_answer ?? '—', (facts.rings_to_answer ?? 0) >= 5],
    ['Hold', facts.put_on_hold ? 'Yes' : 'No', facts.put_on_hold],
    ['Hold time', `${facts.hold_time_seconds ?? 0}s`, (facts.hold_time_seconds ?? 0) > 60],
    ['Transfers', facts.transfer_count, facts.transfer_count > 0],
    ['Abandoned', facts.call_abandoned_by_restaurant ? 'Yes' : 'No', facts.call_abandoned_by_restaurant],
    ['Interrupts', facts.interruption_count, facts.interruption_count >= 3],
    ['Repeats', facts.repeated_information_count, facts.repeated_information_count >= 2],
    ['Upsell', facts.upsell_attempted ? 'Yes' : 'No', false],
    ['Effort', `${facts.customer_effort_score}/5`, facts.customer_effort_score >= 4],
  ];

  return (
    <div
      style={{
        marginTop: 20,
        display: 'grid',
        gridTemplateColumns: 'repeat(5, 1fr)',
        gap: 0,
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: 10,
        overflow: 'hidden',
      }}
    >
      {cells.map(([label, value, isProblem], i) => (
        <div
          key={label}
          style={{
            padding: '12px 14px',
            borderRight: (i + 1) % 5 === 0 ? 'none' : '1px solid var(--border)',
            borderBottom: i < 5 ? '1px solid var(--border)' : 'none',
          }}
        >
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 10,
              fontWeight: 600,
              letterSpacing: '0.1em',
              textTransform: 'uppercase',
              color: 'var(--ink-muted)',
              marginBottom: 4,
            }}
          >
            {label}
          </div>
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 14,
              fontWeight: 500,
              color: isProblem ? 'var(--hot-fg)' : 'var(--ink)',
            }}
          >
            {value}
          </div>
        </div>
      ))}
    </div>
  );
}

function LeadDetails({ lead }: { lead: Lead }) {
  return (
    <section>
      <header
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          fontWeight: 600,
          letterSpacing: '0.12em',
          textTransform: 'uppercase',
          color: 'var(--ink-muted)',
          marginBottom: 10,
        }}
      >
        LEAD DETAILS
      </header>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', columnGap: 32 }}>
        <div>
          <KV label="Phone" value={lead.phone_display} mono />
          <KV label="Address" value={lead.address ?? '—'} />
          <KV label="Website" value={lead.website ?? '—'} />
          <KV label="Cuisine" value={lead.cuisine_type ?? '—'} />
        </div>
        <div>
          <KV label="Google reviews" value={lead.google_reviews_count?.toLocaleString() ?? '—'} mono />
          <KV label="Source" value="Round 2" />
          <KV label="Owner" value="—" />
          <KV label="Last contact" value="—" />
        </div>
      </div>
    </section>
  );
}
