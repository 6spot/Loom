export default function ChronicleIcon({ name }: { name: "arrow" | "search" | "more" | "time" }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {name === "arrow" ? <path d="M4 12h15m-6-6 6 6-6 6" /> : null}
    {name === "search" ? <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 5 5" /></> : null}
    {name === "more" ? <><circle cx="5" cy="12" r=".8" /><circle cx="12" cy="12" r=".8" /><circle cx="19" cy="12" r=".8" /></> : null}
    {name === "time" ? <><path d="M6 3v18M11 5h9M11 12h6M11 19h9" /><circle cx="6" cy="12" r="2" /></> : null}
  </svg>;
}
