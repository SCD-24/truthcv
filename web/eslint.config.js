/** ESLint flat config for the web app: JS + TypeScript recommended rules,
 * React hooks rules, and jsx-a11y accessibility rules. Both plugins are
 * required — src/ carries eslint-disable comments naming their rules. */
import js from "@eslint/js";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import jsxA11y from "eslint-plugin-jsx-a11y";
import globals from "globals";

export default tseslint.config(
  { ignores: ["dist/", "node_modules/"] },
  {
    files: ["**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: {
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
      "jsx-a11y": jsxA11y,
    },
    rules: {
      ...jsxA11y.flatConfigs.recommended.rules,
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
      // `_`-prefixed names are this codebase's marker for intentionally unused.
      "@typescript-eslint/no-unused-vars": [
        "error",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          caughtErrorsIgnorePattern: "^_",
        },
      ],
      // MUI components manage their own autofocus; raw DOM autoFocus stays an error.
      "jsx-a11y/no-autofocus": ["error", { ignoreNonDOM: true }],
    },
  },
);
