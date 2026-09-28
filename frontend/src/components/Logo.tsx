export default function Logo({ className = "h-8 w-8" }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden
    >
      <rect width="32" height="32" rx="8" fill="#0F172A" />
      <path
        d="M9 10C9 9.44772 9.44772 9 10 9H17C19.7614 9 22 11.2386 22 14C22 16.7614 19.7614 19 17 19H13V23H9V10ZM13 15H17C17.5523 15 18 14.5523 18 14C18 13.4477 17.5523 13 17 13H13V15Z"
        fill="#F8FAFC"
      />
      <circle cx="21" cy="22" r="2" fill="#10B981" />
    </svg>
  );
}
