import { AppShell } from '@/components/app-shell';
import { GenerationCenter } from '@/components/generation-center';

export default function GenerationPage() {
  return <AppShell current="generation"><GenerationCenter /></AppShell>;
}
