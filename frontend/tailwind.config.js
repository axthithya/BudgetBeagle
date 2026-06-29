/** @type {import("tailwindcss").Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      colors: {
        cloud: {
          ink: "#090b10",
          panel: "#111722",
          line: "#283142",
          orange: "#ff9a3d",
          cyan: "#2dd4bf",
          green: "#34d399",
        },
      },
    },
  },
  plugins: [],
};