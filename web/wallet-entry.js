import { createAppKit } from '@reown/appkit'
import { EthersAdapter } from '@reown/appkit-adapter-ethers'
import { defineChain } from '@reown/appkit/networks'

const buttons = [...document.querySelectorAll('[data-wallet-button]')]
const studionet = defineChain({
  id: 61999,
  caipNetworkId: 'eip155:61999',
  chainNamespace: 'eip155',
  name: 'GenLayer Studionet',
  nativeCurrency: { name: 'GEN', symbol: 'GEN', decimals: 18 },
  rpcUrls: { default: { http: ['https://studio.genlayer.com/api'] } },
  blockExplorers: { default: { name: 'GenLayer Explorer', url: 'https://explorer-studio.genlayer.com' } }
})

function inform(message) {
  let toast = document.getElementById('wallet-toast')
  if (!toast) {
    toast = document.createElement('div')
    toast.id = 'wallet-toast'
    toast.setAttribute('role', 'status')
    document.body.append(toast)
  }
  toast.textContent = message
  clearTimeout(inform.timer)
  inform.timer = setTimeout(() => { toast.textContent = '' }, 6000)
}

function display(account) {
  const address = account?.address
  for (const button of buttons) {
    const label = button.querySelector('[data-wallet-label]')
    if (label) label.textContent = address ? `${address.slice(0, 6)}…${address.slice(-4)}` : 'Connect wallet'
    button.classList.toggle('connected', Boolean(address))
    button.setAttribute('aria-label', address ? `Wallet ${address}. Open account menu` : 'Connect wallet')
  }
  document.dispatchEvent(new CustomEvent('clintr:wallet', { detail: { address: address || null } }))
}

let modalPromise

async function init() {
  let projectId = ''
  try {
    const response = await fetch('/wallet/config', { cache: 'no-store' })
    if (response.ok) projectId = (await response.json()).projectId?.trim() || ''
  } catch {}

  if (!projectId) throw new Error('Wallet connection needs a Reown project ID. The site owner can set CLINTR_REOWN_PROJECT_ID to enable it.')

  try {
    const modal = createAppKit({
      adapters: [new EthersAdapter()],
      networks: [studionet],
      defaultNetwork: studionet,
      projectId,
      metadata: {
        name: 'Clintr',
        description: 'Verifiable edge compute grid',
        url: window.location.origin,
        icons: [`${window.location.origin}/assets/favicon.svg`]
      },
      features: { analytics: false, onramp: false, swaps: false },
      themeMode: 'dark',
      themeVariables: { '--w3m-accent': '#c6f279', '--w3m-border-radius-master': '8px' }
    })
    display(modal.getAccount('eip155'))
    modal.subscribeAccount(account => display(account), 'eip155')
    return modal
  } catch (error) {
    console.error('Clintr Reown setup failed', error)
    throw new Error('Wallet connection is temporarily unavailable.')
  }
}

export async function openWallet() {
  try {
    const modal = await (modalPromise ||= init())
    await modal.open({ view: modal.getAccount('eip155')?.address ? 'Account' : 'Connect' })
  } catch (error) {
    modalPromise = undefined
    inform(error.message)
  }
}
