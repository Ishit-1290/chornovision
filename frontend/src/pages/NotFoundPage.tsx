import { Link as RouterLink } from 'react-router-dom';
import { Link, Stack, Typography } from '@mui/material';

export function NotFoundPage() {
  return (
    <Stack spacing={2} sx={{ py: 8, alignItems: 'center' }}>
      <Typography variant="h1">Page not found</Typography>
      <Typography color="text.secondary">The page you requested does not exist.</Typography>
      <Link component={RouterLink} to="/">
        Return to overview
      </Link>
    </Stack>
  );
}
