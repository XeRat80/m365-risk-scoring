import {ArrowLeft, Radar} from "lucide-react";
import Link from "next/link";
import {Button} from "@/components/ui/button";

export default function NotFound() {
  return (
    <main className="center-stage">
      <div className="max-w-lg text-center">
        <span className="mx-auto grid size-12 place-items-center rounded-xl bg-primary/10 text-primary ring-1 ring-primary/15"><Radar/></span>
        <p className="page-eyebrow mt-6">404 · route not found</p>
        <h1 className="mt-3 text-4xl font-semibold tracking-[-.05em]">This workspace view does not exist.</h1>
        <p className="mt-3 text-sm leading-6 text-muted-foreground">Return to the live tenant overview and continue from a verified navigation path.</p>
        <Button className="mt-6" asChild><Link href="/"><ArrowLeft/>Return to overview</Link></Button>
      </div>
    </main>
  );
}
