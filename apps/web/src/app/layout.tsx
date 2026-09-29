import type {Metadata} from "next";
import "./globals.css";
import {Providers} from "@/components/providers";

export const metadata: Metadata = {
  title: {
    default: "M365 Risk Command",
    template: "%s · M365 Risk Command",
  },
  description: "Privacy-preserving Microsoft 365 user risk operations",
  applicationName: "M365 Risk Command",
  keywords: ["Microsoft 365", "user risk", "mail security", "identity protection", "offline simulation"],
  robots: {index: false, follow: false},
};

export default function RootLayout({children}: Readonly<{children: React.ReactNode}>) {
  return (
    <html lang="en" className="dark">
      <body><Providers>{children}</Providers></body>
    </html>
  );
}
