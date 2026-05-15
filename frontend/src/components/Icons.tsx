interface IconProps {
  s?: number;
}

export const Icon = {
  Phone: ({ s = 16 }: IconProps) => (
    <svg width={s} height={s} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 3.5a1 1 0 0 1 1-1h2l1.5 3-1.5 1a8 8 0 0 0 3.5 3.5l1-1.5 3 1.5v2a1 1 0 0 1-1 1A10 10 0 0 1 3 3.5Z" />
    </svg>
  ),
  Search: ({ s = 16 }: IconProps) => (
    <svg width={s} height={s} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round">
      <circle cx="7" cy="7" r="4.5" />
      <path d="m10.5 10.5 3 3" />
    </svg>
  ),
  Inbox: ({ s = 18 }: IconProps) => (
    <svg width={s} height={s} viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2.5 10v4a1 1 0 0 0 1 1h11a1 1 0 0 0 1-1v-4" />
      <path d="M2.5 10 4 4h10l1.5 6" />
      <path d="M2.5 10h3l1 2h5l1-2h3" />
    </svg>
  ),
  Calls: ({ s = 18 }: IconProps) => (
    <svg width={s} height={s} viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3.5 3.5a1 1 0 0 1 1-1H7l1.5 3.5-2 1.2a9 9 0 0 0 3.8 3.8l1.2-2L15 10.5v2.5a1 1 0 0 1-1 1A11 11 0 0 1 3.5 3.5Z" />
    </svg>
  ),
  Library: ({ s = 18 }: IconProps) => (
    <svg width={s} height={s} viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="12" height="12" rx="1.5" />
      <path d="M3 7h12M7 3v12" />
    </svg>
  ),
  Insights: ({ s = 18 }: IconProps) => (
    <svg width={s} height={s} viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 14V8M7 14V5M11 14v-4M15 14V3" />
    </svg>
  ),
  Settings: ({ s = 18 }: IconProps) => (
    <svg width={s} height={s} viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="9" cy="9" r="2" />
      <path d="M9 2v2M9 14v2M2 9h2M14 9h2M4 4l1.5 1.5M12.5 12.5 14 14M4 14l1.5-1.5M12.5 5.5 14 4" />
    </svg>
  ),
  Sparkle: ({ s = 14 }: IconProps) => (
    <svg width={s} height={s} viewBox="0 0 16 16" fill="currentColor">
      <path d="M8 1.5 9 6l4.5 1L9 8l-1 4.5L7 8 2.5 7 7 6Z" />
    </svg>
  ),
  Globe: ({ s = 14 }: IconProps) => (
    <svg width={s} height={s} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round">
      <circle cx="8" cy="8" r="5.5" />
      <path d="M2.5 8h11M8 2.5c2 1.5 2 9.5 0 11M8 2.5c-2 1.5-2 9.5 0 11" />
    </svg>
  ),
  Star: ({ s = 14 }: IconProps) => (
    <svg width={s} height={s} viewBox="0 0 16 16" fill="currentColor">
      <path d="M8 1.5 10 6l5 .5-3.7 3.4 1.1 4.9L8 12.3l-4.4 2.5 1.1-4.9L1 6.5 6 6Z" />
    </svg>
  ),
  Play: ({ s = 16 }: IconProps) => (
    <svg width={s} height={s} viewBox="0 0 16 16" fill="currentColor">
      <path d="M5 3.5v9l8-4.5-8-4.5Z" />
    </svg>
  ),
  Pause: ({ s = 16 }: IconProps) => (
    <svg width={s} height={s} viewBox="0 0 16 16" fill="currentColor">
      <rect x="4" y="3.5" width="3" height="9" rx="0.5" />
      <rect x="9" y="3.5" width="3" height="9" rx="0.5" />
    </svg>
  ),
};
