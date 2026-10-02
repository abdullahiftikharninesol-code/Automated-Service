import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Missed Lead Rescue",
  description: "Simple lead follow-up for HVAC teams",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
