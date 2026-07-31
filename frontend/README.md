# ASPIRE AI — web client

The chat interface for ASPIRE AI. It talks to the FastAPI service in
[`../backend`](../backend), which owns the agent, the knowledge base, and
conversation memory.

## Getting started

**The backend must be running**, or every question comes back with "I could not
reach the ASPIRE service." Start it first — see the
[backend README](../backend/README.md):

```bash
cd ../backend && uv run uvicorn app.main:app --reload --port 8000
```

Then:

```bash
cp .env.example .env      # optional; the default already points at :8000
bun install
bun --bun run dev         # http://localhost:3000
```

## Voice

The mic, read-aloud, and voice options all talk to the backend's `app/voice/`
module. If that module is off (or the backend is down), `/api/voice/config` fails
and the mic renders disabled as "Voice unavailable" — the rest of the chat is
unaffected.

| Concern | Where it lives |
| --- | --- |
| Voice HTTP calls | `src/lib/aspire/voice.ts` |
| Recording, playback, consent, notes | `src/lib/aspire/use-voice.ts` |
| Consent, listening, transcribing, notes UI | `src/components/chat/Voice.tsx` |

**A transcript is never sent on its own.** It lands in the composer so it can be
corrected first, which is exactly what the consent panel promises.

**Read answers aloud** (voice options → the switch) plays each answer as it
arrives, using the full reply rather than waiting for the typewriter. It only
fires for new answers: reopening a past conversation restores it silently.
Speed, language, and the switch itself persist in `localStorage`.

Audio stops whenever the conversation moves on — a new question, "Try again",
"New chat", or opening a past conversation.

If a browser refuses to auto-start audio, the answer simply stays on **Play**
rather than reporting a failure.

## How it connects

| Concern | Where it lives |
| --- | --- |
| HTTP calls, timeouts, error copy | `src/lib/aspire/api.ts` |
| Markdown reply → transcript blocks | `src/lib/aspire/knowledge.ts` |
| Turn state, streaming, thread id | `src/lib/aspire/use-conversation.ts` |
| Conversation history (this browser) | `src/lib/aspire/history.ts` |

`api.ts` is the only module that knows a server exists. Point it somewhere else
with `VITE_ASPIRE_API_URL`.

**Conversation memory** lives on the backend, keyed by a `thread_id` the client
stores per conversation. **History** in the left rail is `localStorage` in this
browser, because Phase 1 of the backend has no database. The two are independent:
after the backend restarts, an old conversation still reads back from the rail,
but the assistant no longer remembers it.

The reply is not streamed — Phase 1 returns one JSON response, and the transcript
reveals it with a typewriter effect. `prefers-reduced-motion` skips straight to
the finished answer.

## Building for production

```bash
bun --bun run build
```

## Styling

This project uses [Tailwind CSS](https://tailwindcss.com/) for styling.

### Removing Tailwind CSS

If you prefer not to use Tailwind CSS:

1. Replace the Tailwind import in `src/styles.css` with your own styles
2. Remove `tailwindcss()` from the plugins array in `vite.config.ts`
3. Remove `@tailwindcss/vite` and `tailwindcss` from `package.json`

Note that `src/styles.css` defines the ASPIRE design tokens by hand and only uses
Tailwind for its reset and `@theme`, so most of the styling survives either way.

## Linting & Formatting

This project uses [Biome](https://biomejs.dev/) for linting and formatting. The following scripts are available:


```bash
bun --bun run lint
bun --bun run format
bun --bun run check
```



## Routing

This project uses [TanStack Router](https://tanstack.com/router) with file-based routing. Routes are managed as files in `src/routes`.

### Adding A Route

To add a new route to your application just add a new file in the `./src/routes` directory.

TanStack will automatically generate the content of the route file for you.

Now that you have two routes you can use a `Link` component to navigate between them.

### Adding Links

To use SPA (Single Page Application) navigation you will need to import the `Link` component from `@tanstack/react-router`.

```tsx
import { Link } from "@tanstack/react-router";
```

Then anywhere in your JSX you can use it like so:

```tsx
<Link to="/about">About</Link>
```

This will create a link that will navigate to the `/about` route.

More information on the `Link` component can be found in the [Link documentation](https://tanstack.com/router/v1/docs/framework/react/api/router/linkComponent).

### Using A Layout

In the File Based Routing setup the layout is located in `src/routes/__root.tsx`. Anything you add to the root route will appear in all the routes. The route content will appear in the JSX where you render `{children}` in the `shellComponent`.

Here is an example layout that includes a header:

```tsx
import { HeadContent, Scripts, createRootRoute } from '@tanstack/react-router'

export const Route = createRootRoute({
  head: () => ({
    meta: [
      { charSet: 'utf-8' },
      { name: 'viewport', content: 'width=device-width, initial-scale=1' },
      { title: 'My App' },
    ],
  }),
  shellComponent: ({ children }) => (
    <html lang="en">
      <head>
        <HeadContent />
      </head>
      <body>
        <header>
          <nav>
            <Link to="/">Home</Link>
            <Link to="/about">About</Link>
          </nav>
        </header>
        {children}
        <Scripts />
      </body>
    </html>
  ),
})
```

More information on layouts can be found in the [Layouts documentation](https://tanstack.com/router/latest/docs/framework/react/guide/routing-concepts#layouts).

## Server Functions

TanStack Start provides server functions that allow you to write server-side code that seamlessly integrates with your client components.

```tsx
import { createServerFn } from '@tanstack/react-start'

const getServerTime = createServerFn({
  method: 'GET',
}).handler(async () => {
  return new Date().toISOString()
})

// Use in a component
function MyComponent() {
  const [time, setTime] = useState('')
  
  useEffect(() => {
    getServerTime().then(setTime)
  }, [])
  
  return <div>Server time: {time}</div>
}
```

## API Routes

You can create API routes by using the `server` property in your route definitions:

```tsx
import { createFileRoute } from '@tanstack/react-router'
import { json } from '@tanstack/react-start'

export const Route = createFileRoute('/api/hello')({
  server: {
    handlers: {
      GET: () => json({ message: 'Hello, World!' }),
    },
  },
})
```

## Data Fetching

There are multiple ways to fetch data in your application. You can use TanStack Query to fetch data from a server. But you can also use the `loader` functionality built into TanStack Router to load the data for a route before it's rendered.

For example:

```tsx
import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/people')({
  loader: async () => {
    const response = await fetch('https://swapi.dev/api/people')
    return response.json()
  },
  component: PeopleComponent,
})

function PeopleComponent() {
  const data = Route.useLoaderData()
  return (
    <ul>
      {data.results.map((person) => (
        <li key={person.name}>{person.name}</li>
      ))}
    </ul>
  )
}
```

Loaders simplify your data fetching logic dramatically. Check out more information in the [Loader documentation](https://tanstack.com/router/latest/docs/framework/react/guide/data-loading#loader-parameters).


# Demo files

Files prefixed with `demo` can be safely deleted. They are there to provide a starting point for you to play around with the features you've installed.


# Learn More

You can learn more about all of the offerings from TanStack in the [TanStack documentation](https://tanstack.com).

For TanStack Start specific documentation, visit [TanStack Start](https://tanstack.com/start).
