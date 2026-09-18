import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: {
    default: "Curator — See both sides of the pool",
    template: "%s | Curator",
  },
  description:
    "An LP workspace for concentrated liquidity. Rank pairs by fees, depth, and risk. Private watchlist. Sign in with your wallet or email; no transactions.",
};
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <a href="#main" className="skip">
          Skip to content
        </a>
        {children}
      </body>
    </html>
  );
}
