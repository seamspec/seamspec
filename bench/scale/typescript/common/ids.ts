// Record ids such as `ord-000042`.
export const LARGEST = 999999;

export function makeId(prefix: string, number: number): string {
  if (!/^[A-Za-z]+$/.test(prefix)) throw new Error(`bad prefix: ${prefix}`);
  if (!Number.isInteger(number) || number < 0 || number > LARGEST) throw new Error(`bad number: ${number}`);
  return `${prefix.toLowerCase()}-${String(number).padStart(6, "0")}`;
}

export function parseId(text: string): [string, number] {
  const match = /^([a-z]+)-(\d{6})$/.exec(text);
  if (!match) throw new Error(`bad id: ${text}`);
  return [match[1], Number(match[2])];
}
