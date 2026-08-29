import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans, IBM_Plex_Serif } from "next/font/google";
import "./globals.css";

const sans = IBM_Plex_Sans({
  subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-plex-sans",
});
const serif = IBM_Plex_Serif({
  subsets: ["latin"], weight: ["400", "500"], style: ["normal", "italic"],
  variable: "--font-plex-serif",
});
const mono = IBM_Plex_Mono({
  subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-plex-mono",
});

export const metadata: Metadata = {
  title: "VendorDiscoveryShortcut",
  description: "Tell it what you want to make. It finds the suppliers, and shows its sources.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${serif.variable} ${mono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
