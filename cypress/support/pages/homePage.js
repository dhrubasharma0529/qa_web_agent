class HomePage {
  visit() {
    cy.visit('/');
  }

  downloadResume() {
    cy.get('a[href="/assets/MishanCV.pdf"]').should('have.attr', 'href').and('include', '/assets/MishanCV.pdf');
  }

  scrollToExperienceSection() {
    cy.get('h2').contains('Experience').scrollIntoView();
  }

  scrollToEducationSection() {
    cy.get('h2').contains('Education').scrollIntoView();
  }

  scrollToCaseStudiesSection() {
    cy.get('h2').contains('Case Studies').scrollIntoView();
  }

  checkProjectLinks() {
    cy.get('[aria-label="View WhosLive.io project"]').should('exist');
    cy.get('[aria-label="View Agent Manager project"]').should('exist');
    cy.get('[aria-label="View FindTheCourses project"]').should('exist');
    cy.get('[aria-label="View XcelPay Wallet project"]').should('exist');
    cy.get('[aria-label="View XcelTrip project"]').should('exist');
    cy.get('[aria-label="View Enchanted Weddings project"]').should('exist');
  }

  accessContactLinks() {
    cy.get('a[href="https://github.com/Mishankhatri"]').should('have.attr', 'href').and('include', 'github.com');
    cy.get('a[href="https://www.linkedin.com/in/mishankhatri"]').should('have.attr', 'href').and('include', 'linkedin.com');
    cy.get('a[href="mailto:mishankhatri490@gmail.com"]').should('have.attr', 'href').and('include', 'mailto:');
  }
}

module.exports = new HomePage();