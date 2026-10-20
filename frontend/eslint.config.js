import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "src/api/schema.d.ts"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["src/**/*.{ts,tsx}"],
    languageOptions: { globals: { ...globals.browser } },
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
      // The API layer is the only place allowed to call fetch directly (src/api/*), see CLAUDE.md.
      "no-restricted-globals": ["error", { name: "fetch", message: "Use the typed client in src/api/ instead of fetch." }],
    },
  },
  {
    files: ["src/api/**/*.{ts,tsx}", "src/**/*.test.{ts,tsx}", "src/test/**"],
    rules: { "no-restricted-globals": "off" },
  },
);
