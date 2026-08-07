/** @type {import('tailwindcss').Config} */

// Design system: minimal black. See STRATEGY.md §8.
//
// Two rules do most of the work here:
//   1. There is no chromatic accent. Emphasis is white-on-black inversion, type weight,
//      and space. `accent` is white on purpose — the old #ff7a17 sunset was applied 110
//      times across src/, which makes it a second background colour, not an accent.
//   2. One radius (2px). The previous theme mixed five (full/2xl/xl/lg/md).
//
// Colour is reserved for danger. Everything else — confidence, status, selection — is
// expressed in neutral steps, because a five-hue status rainbow is the loudest AI tell
// in a dark product UI.
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        canvas: {
          DEFAULT: '#000000',   // true black
          card: '#0b0b0b',      // raised surfaces
          soft: '#060606',      // wells, inputs, code blocks
          hover: '#131313'
        },
        ink: {
          DEFAULT: '#ededed',   // never pure #fff on true black — it vibrates
          body: '#9e9e9e',
          mute: '#6b6b6b',
          faint: '#444444'
        },
        hairline: {
          DEFAULT: '#1a1a1a',
          light: '#222222',
          bright: '#2b2b2b'
        },
        // The only accent. Named `sunset` purely so the ~110 existing call sites keep
        // compiling; it is white. Do not reintroduce a hue here.
        accent: {
          sunset: '#ffffff',
          sunsetsoft: 'rgba(255, 255, 255, 0.06)'
        },
        danger: {
          DEFAULT: '#ff5c4d',
          soft: 'rgba(255, 92, 77, 0.10)'
        }
      },
      borderRadius: {
        // One radius. `sm`/`DEFAULT`/`md`/`lg`/`xl`/`2xl` all collapse to 2px so that any
        // stray legacy class can't reintroduce a second shape language. `full` stays for
        // genuine circles (spinners), not for pills.
        none: '0px',
        sm: '2px',
        DEFAULT: '2px',
        md: '2px',
        lg: '2px',
        xl: '2px',
        '2xl': '2px',
        '3xl': '2px',
        full: '9999px'
      },
      fontFamily: {
        // Geist over Inter — Inter + near-black + one accent is the canonical LLM default,
        // and Geist Mono is already loaded so the pairing costs nothing.
        sans: ['Geist', 'Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['Geist Mono', 'JetBrains Mono', 'ui-monospace', 'monospace']
      },
      letterSpacing: {
        tightest: '-0.04em',
        tighter: '-0.025em',
        tight: '-0.015em',
        // Kept so `tracking-widestmono` compiles, but deliberately near-zero: the
        // uppercase wide-tracking eyebrow is the tell we're removing.
        widestmono: '0.01em'
      },
      transitionDuration: {
        DEFAULT: '120ms'
      }
    },
  },
  plugins: [],
}
