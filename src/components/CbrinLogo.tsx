import React from 'react';

interface CbrinLogoProps {
  className?: string;
  size?: number;
  useGradient?: boolean;
}

/**
 * Official CBRIN Vector Logo Mark Component
 * Extracted from CBRIN-logo/vector/ with padded viewBox (-3 -3 38 38)
 * to prevent corner node clipping.
 */
export const CbrinLogo: React.FC<CbrinLogoProps> = ({
  className = 'w-7 h-7',
  useGradient = true,
}) => {
  return (
    <div
      className={`relative rounded-sm bg-[#121215] border border-hairline flex items-center justify-center shrink-0 transition-all duration-300 group-hover:border-accent-sunset/60 group-hover:bg-canvas-card ${className}`}
    >
      <svg
        viewBox="-3 -3 38 38"
        xmlns="http://www.w3.org/2000/svg"
        className="w-4 h-4 transition-transform duration-300 group-hover:scale-105"
      >
        <defs>
          <linearGradient id="cbrin-sunset-grad" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#ff7a17" />
            <stop offset="100%" stopColor="#ff3b00" />
          </linearGradient>
        </defs>
        <g fill={useGradient ? "url(#cbrin-sunset-grad)" : "currentColor"}>
          {/* Main Diagonal Connector Lines */}
          <path d="m15.965 16.258.707-.707 10.39 10.39-.707.707z" />
          <path d="M4.935 26.357 26.018 5.274l.707.707L5.642 27.065z" />
          
          {/* Bounding Box Nodes */}
          <path d="M31 1v4.194h-4.194V1zm1-1h-6.194v6.194H32zM31 26.806V31h-4.194v-4.194zm1-1h-6.194V32H32zM5.194 26.806V31H1v-4.194zm1-1H0V32h6.194z" />
        </g>
      </svg>
    </div>
  );
};
