import { dirname } from "path";
import { fileURLToPath } from "url";
import { FlatCompat } from "@eslint/eslintrc";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const compat = new FlatCompat({
  baseDirectory: __dirname,
});

const eslintConfig = [
  // ✅ Globally ignore generated Prisma files
  {
    ignores: ["src/generated/**"],
  },

  // ✅ Next.js + TypeScript core rules
  ...compat.extends("next/core-web-vitals", "next/typescript"),

  // ✅ TypeScript rules for your app code
  {
    files: ["**/*.ts", "**/*.tsx"],
    parser: "@typescript-eslint/parser",
    plugins: ["@typescript-eslint"],
    rules: {
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/no-unused-expressions": "error",
    },
  },
];

export default eslintConfig;
