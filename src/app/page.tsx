import Link from "next/link";
import UserNav from '@/components/auth/user-nav.client'
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

export default function Home() {
  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="bg-white shadow">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between h-16">
            <div className="flex items-center">
              <h1 className="text-xl font-semibold">Lexon</h1>
            </div>
            <div className="flex items-center space-x-4">
              <Link href="/import">
                <Button variant="outline">Import KG</Button>
              </Link>
              <Link href="/search">
                <Button variant="outline">Search</Button>
              </Link>
              <UserNav />
            </div>
          </div>
        </div>
      </nav>
      
      <main className="max-w-7xl mx-auto py-6 sm:px-6 lg:px-8">
        <div className="px-4 py-6 sm:px-0">
          <Card className="h-96 flex items-center justify-center">
            <CardContent className="text-center">
              <h2 className="text-2xl font-bold text-gray-500">
                Welcome to your Next.js app with authentication!
              </h2>
            </CardContent>
          </Card>
        </div>
      </main>
    </div>
  );
}
