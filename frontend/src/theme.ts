import { createTheme } from '@mui/material/styles';

/**
 * A restrained dark theme for a monitoring dashboard: high contrast for status colours and
 * compact typography so timelines and tables stay readable.
 */
export const theme = createTheme({
  palette: {
    mode: 'dark',
    primary: { main: '#4f9dff' },
    secondary: { main: '#38b2ac' },
    success: { main: '#38a169' },
    warning: { main: '#dd9b3c' },
    error: { main: '#e05252' },
    background: { default: '#101418', paper: '#181f26' },
  },
  shape: { borderRadius: 8 },
  typography: {
    fontSize: 14,
    h1: { fontSize: '1.6rem', fontWeight: 600 },
    h2: { fontSize: '1.3rem', fontWeight: 600 },
    h3: { fontSize: '1.1rem', fontWeight: 600 },
    button: { textTransform: 'none' },
  },
  components: {
    MuiPaper: { defaultProps: { variant: 'outlined' } },
    MuiTableCell: { styleOverrides: { root: { borderColor: 'rgba(255,255,255,0.08)' } } },
  },
});
