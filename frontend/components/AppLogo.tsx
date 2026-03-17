export function AppIcon({ className }: { className?: string }) {
    return (
        <svg
            className={className}
            viewBox="0 0 24 24"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
        >
            {/* Chat bubble */}
            <path
                d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"
                fill="white"
                fillOpacity="0.2"
                stroke="white"
                strokeWidth="1.5"
                strokeLinejoin="round"
            />
            {/* Network edges */}
            <line x1="8.5" y1="8.5" x2="15.5" y2="8.5" stroke="white" strokeWidth="1.4" strokeLinecap="round" />
            <line x1="8.5" y1="8.5" x2="12"   y2="13.5" stroke="white" strokeWidth="1.4" strokeLinecap="round" />
            <line x1="15.5" y1="8.5" x2="12"  y2="13.5" stroke="white" strokeWidth="1.4" strokeLinecap="round" />
            {/* Network nodes */}
            <circle cx="8.5"  cy="8.5"  r="1.8" fill="white" />
            <circle cx="15.5" cy="8.5"  r="1.8" fill="white" />
            <circle cx="12"   cy="13.5" r="1.8" fill="white" />
        </svg>
    )
}
