import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import SessionProviderWrapper from "@/components/providers/session-provider.client";
import Link from "next/link";
import Button from "@/components/ui/button";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Lexon",
  description: "Lexon is a platform for legal research and analysis.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        <header className="border-b bg-white">
          <div className="mx-auto max-w-5xl px-4">
            <div className="flex items-center justify-between py-3">
              <Link href="/search" className="text-2xl font-semibold tracking-tight">
                Lexon
              </Link>
              <div className="flex items-center gap-3">
                <Link href="/search" className="text-gray-700 hover:text-gray-900">
                  Search
                </Link>
                <Link href="/import" className="text-gray-700 hover:text-gray-900">
                  Import
                </Link>
                <Link href="/auth/signout">
                  <Button variant="outline">Sign out</Button>
                </Link>
              </div>
            </div>
          </div>
        </header>
        <SessionProviderWrapper>
          {children}
        </SessionProviderWrapper>
      </body>
    </html>
  );
}
