const PATHS = {
  camera: (
    <>
      <rect height="9" rx="1.5" width="10" x="1" y="3.5" />
      <path d="m11 6 4-2v8l-4-2" />
    </>
  ),
  check: <path d="m4 9 3 3 6-7" />,
  chevron: <path d="m5 7 3 3 3-3" />,
  expand: (
    <>
      <path d="M6 2H2v4M10 2h4v4M6 14H2v-4M10 14h4v-4" />
      <path d="m2 6 4-4M10 2l4 4M2 10l4 4M10 14l4-4" />
    </>
  ),
  person: (
    <>
      <circle cx="8" cy="5" r="2" />
      <path d="M3.5 14c.4-3 1.9-4.5 4.5-4.5s4.1 1.5 4.5 4.5" />
    </>
  ),
  search: (
    <>
      <circle cx="7" cy="7" r="4.5" />
      <path d="m10.5 10.5 3 3" />
    </>
  ),
  warning: (
    <>
      <path d="M8 2.5 15 14H1L8 2.5Z" />
      <path d="M8 6.5v3.5M8 12v.1" />
    </>
  ),
  bell: (
    <>
      <path d="M4 11V7a4 4 0 0 1 8 0v4l1 1.5H3L4 11Z" />
      <path d="M6.5 14a1.6 1.6 0 0 0 3 0" />
    </>
  ),
  bellOff: (
    <>
      <path d="M4 11V7a4 4 0 0 1 8 0v4l1 1.5H3L4 11Z" />
      <path d="M6.5 14a1.6 1.6 0 0 0 3 0" />
      <path d="m2 2 12 12" />
    </>
  ),
  volume: (
    <>
      <path d="M2.5 6v4h2.5L8.5 13V3L5 6H2.5Z" />
      <path d="M11 5.5a3.5 3.5 0 0 1 0 5" />
    </>
  ),
  close: <path d="m4 4 8 8M12 4l-8 8" />,
  pin: (
    <>
      <path d="M8 14s4.5-4 4.5-7.5a4.5 4.5 0 0 0-9 0C3.5 10 8 14 8 14Z" />
      <circle cx="8" cy="6.5" r="1.5" />
    </>
  ),
}

export default function Icon({ name, size = 16 }) {
  return (
    <svg aria-hidden="true" fill="none" height={size} viewBox="0 0 16 16" width={size}>
      <g stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5">
        {PATHS[name]}
      </g>
    </svg>
  )
}
