const homePage = require('../support/pages/homePage');

describe('Resume download link (PDF)', () => {
  it('Download link is broken or leads to a 404 error', () => {
    homePage.visit();
    cy.get('a[href="/assets/MishanCV.pdf"]').should('have.attr', 'href').and('include', '/assets/MishanCV.pdf');
  });
});