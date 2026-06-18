export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#15202b",
        quiet: "#66788a",
        line: "#d9e2ea",
        paper: "#fbfcfd",
        panel: "#ffffff",
        brand: "#0f766e",
        blue: "#1769c2",
        amber: "#a66b00",
        rose: "#c73652"
      },
      boxShadow: {
        soft: "0 18px 50px rgba(21, 32, 43, 0.08)"
      },
      fontFamily: {
        sans: ["Aptos", "Inter", "Segoe UI Variable", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["Aptos Display", "Segoe UI Variable Display", "Aptos", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["Cascadia Mono", "SFMono-Regular", "Consolas", "monospace"]
      }
    }
  },
  plugins: []
};
