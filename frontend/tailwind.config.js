/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#12203A",
        brand: { 50: "#EEF3FB", 100: "#D9E4F5", 200: "#B3C9EB", 300: "#82A6DB", 400: "#4E7FC7",
                 500: "#2E5FA8", 600: "#234A85", 700: "#1C3B69", 800: "#172F54", 900: "#12203A" },
        // activity types (validated categorical order, slots 1-4)
        trip: "#2a78d6", move: "#eb6834", charge: "#1baf7a", lay: "#eda100",
        // reserved status colours (always paired with icon + label)
        ok: "#0ca30c", warn: "#fab219", serious: "#ec835a", danger: "#d03b3b",
      },
      fontFamily: { sans: ["'Inter'", "system-ui", "sans-serif"] },
      boxShadow: { card: "0 1px 2px rgba(18,32,58,0.06), 0 1px 12px rgba(18,32,58,0.04)" },
    },
  },
  plugins: [],
}
